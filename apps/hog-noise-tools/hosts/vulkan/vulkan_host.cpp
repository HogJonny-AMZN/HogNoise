// HogNoise tools: the Vulkan host harness. noise.spv's five entry points dispatched through Vulkan on a CPU device,
// Mesa's lavapipe, written from hog_noise/shaders/README.md alone: a driver consuming the shipped bytes, where wgpu's
// SPIR-V front end reads them back through naga.
//
// The frames, the refusals and the loop are frames.h's, shared with the HLSL harness; this file is the one back end.
// Each init frame's program is noise.spv itself, once per entry point, and the pipeline names its entry point. It
// opens the first device of type CPU, so a machine with a GPU still runs on lavapipe; none is status 2, naming the
// devices it found. Built by build.sh (g++ and libvulkan-dev); the binary is gitignored.

#include <vulkan/vulkan.h>

#include <algorithm>
#include <cstdint>
#include <cstring>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

#include "../frames.h"

using frames::Backend;
using frames::Bytes;
using frames::Request;
using frames::Unavailable;

namespace {

// a Vulkan create-info, zeroed, with its type: every field a call does not set is zero, as the spec allows
template <typename T>
T info(VkStructureType type) {
    T value{};
    value.sType = type;
    return value;
}

void check(VkResult result, const char* what) {
    if (result != VK_SUCCESS) throw std::runtime_error(std::string(what) + " failed: VkResult " + std::to_string(result));
}

std::string version(uint32_t v) {
    return std::to_string(VK_API_VERSION_MAJOR(v)) + "." + std::to_string(VK_API_VERSION_MINOR(v)) + "." +
           std::to_string(VK_API_VERSION_PATCH(v));
}

// The README's bindings, all in set 0: 0 Params and 6 Grid are uniform buffers, 1 the tables, 2-4 the coordinates
// and 5 the output storage buffers.
constexpr VkDescriptorType kTypes[7] = {
    VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER, VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, VK_DESCRIPTOR_TYPE_STORAGE_BUFFER,
    VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, VK_DESCRIPTOR_TYPE_STORAGE_BUFFER,
    VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER,
};

struct Buffer {
    VkBuffer buffer = VK_NULL_HANDLE;
    VkDeviceMemory memory = VK_NULL_HANDLE;
    VkDeviceSize size = 0;
};

struct Vulkan : Backend {
    VkInstance instance = VK_NULL_HANDLE;
    VkPhysicalDevice physical = VK_NULL_HANDLE;
    VkDevice dev = VK_NULL_HANDLE;
    VkQueue queue = VK_NULL_HANDLE;
    uint32_t family = 0;
    VkPhysicalDeviceMemoryProperties memory{};
    VkDescriptorSetLayout set_layout = VK_NULL_HANDLE;
    VkPipelineLayout layout = VK_NULL_HANDLE;
    std::vector<VkShaderModule> modules;
    std::vector<VkPipeline> pipelines;
    VkCommandPool pool = VK_NULL_HANDLE;
    Buffer tables;

    Vulkan() {
        auto app = info<VkApplicationInfo>(VK_STRUCTURE_TYPE_APPLICATION_INFO);
        app.pApplicationName = "hog-noise vulkan_host";
        app.apiVersion = VK_API_VERSION_1_1;  // SPV_KHR_storage_buffer_storage_class, which noise.spv uses, is core
        auto ici = info<VkInstanceCreateInfo>(VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO);
        ici.pApplicationInfo = &app;
        // Only the loader finding no driver is absence; any other failure is an error, so a broken driver is never
        // read as "not here"
        VkResult made = vkCreateInstance(&ici, nullptr, &instance);
        if (made == VK_ERROR_INCOMPATIBLE_DRIVER)
            throw Unavailable("vkCreateInstance: VK_ERROR_INCOMPATIBLE_DRIVER, no Vulkan driver");
        check(made, "vkCreateInstance");

        uint32_t count = 0;
        check(vkEnumeratePhysicalDevices(instance, &count, nullptr), "vkEnumeratePhysicalDevices");
        std::vector<VkPhysicalDevice> devices(count);
        VkResult listed = vkEnumeratePhysicalDevices(instance, &count, devices.data());
        if (listed != VK_INCOMPLETE) check(listed, "vkEnumeratePhysicalDevices");
        devices.resize(count);
        std::string found;
        VkPhysicalDeviceProperties props{};
        for (VkPhysicalDevice d : devices) {
            VkPhysicalDeviceProperties p{};
            vkGetPhysicalDeviceProperties(d, &p);
            found += std::string(found.empty() ? "" : ", ") + p.deviceName;
            if (p.deviceType == VK_PHYSICAL_DEVICE_TYPE_CPU && physical == VK_NULL_HANDLE) {
                physical = d;
                props = p;
            }
        }
        if (physical == VK_NULL_HANDLE)
            throw Unavailable("no Vulkan device of type CPU (lavapipe); found: " + (found.empty() ? "none" : found));
        if (props.apiVersion < VK_API_VERSION_1_1)
            throw Unavailable(std::string(props.deviceName) + " is Vulkan " + version(props.apiVersion) +
                              ", and noise.spv needs 1.1");
        target = std::string(props.deviceName) + " (Vulkan " + version(props.apiVersion) + ")";
        vkGetPhysicalDeviceMemoryProperties(physical, &memory);

        uint32_t families = 0;
        vkGetPhysicalDeviceQueueFamilyProperties(physical, &families, nullptr);
        std::vector<VkQueueFamilyProperties> qf(families);
        vkGetPhysicalDeviceQueueFamilyProperties(physical, &families, qf.data());
        family = families;
        for (uint32_t i = 0; i < families; ++i)
            if (qf[i].queueFlags & VK_QUEUE_COMPUTE_BIT) {
                family = i;
                break;
            }
        if (family == families) throw Unavailable(target + " has no compute queue");

        float priority = 1.0f;
        auto qci = info<VkDeviceQueueCreateInfo>(VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO);
        qci.queueFamilyIndex = family;
        qci.queueCount = 1;
        qci.pQueuePriorities = &priority;
        auto dci = info<VkDeviceCreateInfo>(VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO);
        dci.queueCreateInfoCount = 1;
        dci.pQueueCreateInfos = &qci;
        check(vkCreateDevice(physical, &dci, nullptr, &dev), "vkCreateDevice");
        vkGetDeviceQueue(dev, family, 0, &queue);

        VkDescriptorSetLayoutBinding bindings[7]{};
        for (uint32_t i = 0; i < 7; ++i) bindings[i] = {i, kTypes[i], 1, VK_SHADER_STAGE_COMPUTE_BIT, nullptr};
        auto sli = info<VkDescriptorSetLayoutCreateInfo>(VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO);
        sli.bindingCount = 7;
        sli.pBindings = bindings;
        check(vkCreateDescriptorSetLayout(dev, &sli, nullptr, &set_layout), "vkCreateDescriptorSetLayout");
        auto pli = info<VkPipelineLayoutCreateInfo>(VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO);
        pli.setLayoutCount = 1;
        pli.pSetLayouts = &set_layout;
        check(vkCreatePipelineLayout(dev, &pli, nullptr, &layout), "vkCreatePipelineLayout");

        auto cpi = info<VkCommandPoolCreateInfo>(VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO);
        cpi.flags = VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT;
        cpi.queueFamilyIndex = family;
        check(vkCreateCommandPool(dev, &cpi, nullptr, &pool), "vkCreateCommandPool");
    }

    ~Vulkan() override {
        if (dev) {
            vkDeviceWaitIdle(dev);
            release(tables);
            for (VkPipeline p : pipelines) vkDestroyPipeline(dev, p, nullptr);
            for (VkShaderModule m : modules) vkDestroyShaderModule(dev, m, nullptr);
            vkDestroyCommandPool(dev, pool, nullptr);
            vkDestroyPipelineLayout(dev, layout, nullptr);
            vkDestroyDescriptorSetLayout(dev, set_layout, nullptr);
            vkDestroyDevice(dev, nullptr);
        }
        if (instance) vkDestroyInstance(instance, nullptr);
    }

    // a host-visible, coherent buffer holding ``data`` (zeros past it), at least one byte: the host writes the inputs
    // and reads the output with no staging copy
    Buffer make(VkBufferUsageFlags usage, const void* data, size_t n, size_t size) {
        Buffer b;
        b.size = std::max<size_t>(size, 4);
        auto bci = info<VkBufferCreateInfo>(VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO);
        bci.size = b.size;
        bci.usage = usage;
        bci.sharingMode = VK_SHARING_MODE_EXCLUSIVE;
        check(vkCreateBuffer(dev, &bci, nullptr, &b.buffer), "vkCreateBuffer");
        try {
            fill(b, data, n);
        } catch (...) {
            release(b);  // the harness reads on after a refusal, so a partial buffer is not left behind
            throw;
        }
        return b;
    }

    // ``make``'s memory: allocated, bound, zeroed and given ``data``
    void fill(Buffer& b, const void* data, size_t n) {
        VkMemoryRequirements req{};
        vkGetBufferMemoryRequirements(dev, b.buffer, &req);
        const VkMemoryPropertyFlags want = VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT;
        uint32_t type = memory.memoryTypeCount;
        for (uint32_t i = 0; i < memory.memoryTypeCount; ++i)
            if ((req.memoryTypeBits & (1u << i)) && (memory.memoryTypes[i].propertyFlags & want) == want) {
                type = i;
                break;
            }
        if (type == memory.memoryTypeCount)
            throw std::runtime_error("no host-visible coherent memory for a buffer of " + std::to_string(b.size));
        auto mai = info<VkMemoryAllocateInfo>(VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO);
        mai.allocationSize = req.size;
        mai.memoryTypeIndex = type;
        check(vkAllocateMemory(dev, &mai, nullptr, &b.memory), "vkAllocateMemory");
        check(vkBindBufferMemory(dev, b.buffer, b.memory, 0), "vkBindBufferMemory");
        void* p = nullptr;
        check(vkMapMemory(dev, b.memory, 0, VK_WHOLE_SIZE, 0, &p), "vkMapMemory");
        std::memset(p, 0, b.size);
        if (n) std::memcpy(p, data, n);
        vkUnmapMemory(dev, b.memory);
    }

    void release(Buffer& b) {
        if (b.buffer) vkDestroyBuffer(dev, b.buffer, nullptr);
        if (b.memory) vkFreeMemory(dev, b.memory, nullptr);
        b = Buffer{};
    }

    void load(const Bytes& t, const std::vector<Bytes>& programs) override {
        tables = make(VK_BUFFER_USAGE_STORAGE_BUFFER_BIT, t.data(), t.size(), t.size());
        for (size_t i = 0; i < programs.size(); ++i) {
            const Bytes& spv = programs[i];
            if (spv.size() % 4 != 0)
                throw std::runtime_error("the program for " + names.at(i) + " is " + std::to_string(spv.size()) +
                                         " bytes, not whole SPIR-V words");
            auto smi = info<VkShaderModuleCreateInfo>(VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO);
            smi.codeSize = spv.size();
            smi.pCode = reinterpret_cast<const uint32_t*>(spv.data());
            VkShaderModule m = VK_NULL_HANDLE;
            check(vkCreateShaderModule(dev, &smi, nullptr, &m), ("vkCreateShaderModule (" + names.at(i) + ")").c_str());
            modules.push_back(m);
            auto cpi = info<VkComputePipelineCreateInfo>(VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO);
            cpi.stage = info<VkPipelineShaderStageCreateInfo>(VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO);
            cpi.stage.stage = VK_SHADER_STAGE_COMPUTE_BIT;
            cpi.stage.module = m;
            cpi.stage.pName = names.at(i).c_str();
            cpi.layout = layout;
            VkPipeline p = VK_NULL_HANDLE;
            check(vkCreateComputePipelines(dev, VK_NULL_HANDLE, 1, &cpi, nullptr, &p),
                  ("vkCreateComputePipelines (" + names.at(i) + ")").c_str());
            pipelines.push_back(p);
        }
    }

    std::vector<float> run(const Request& r) override {
        const size_t out_bytes = size_t(r.n) * r.width * 4;
        static const float unused_axis = 0.0f;  // the README: a one-float buffer for an unused coordinate
        const Bytes grid_bytes = r.grid.empty() ? Bytes(48, 0) : r.grid;  // and 48 zero bytes for an unused Grid
        std::vector<Buffer> owned;
        VkDescriptorPool dpool = VK_NULL_HANDLE;
        VkCommandBuffer cmd = VK_NULL_HANDLE;
        VkFence fence = VK_NULL_HANDLE;
        auto cleanup = [&] {
            if (fence) vkDestroyFence(dev, fence, nullptr);
            if (cmd) vkFreeCommandBuffers(dev, pool, 1, &cmd);
            if (dpool) vkDestroyDescriptorPool(dev, dpool, nullptr);
            for (Buffer& b : owned) release(b);
        };
        try {
            owned.push_back(make(VK_BUFFER_USAGE_UNIFORM_BUFFER_BIT, r.params.data(), r.params.size(), r.params.size()));
            for (int i = 0; i < 3; ++i)
                owned.push_back(i < int(r.axes.size())
                                    ? make(VK_BUFFER_USAGE_STORAGE_BUFFER_BIT, r.axes[i].data(), r.axes[i].size(),
                                           r.axes[i].size())
                                    : make(VK_BUFFER_USAGE_STORAGE_BUFFER_BIT, &unused_axis, 4, 4));
            owned.push_back(make(VK_BUFFER_USAGE_STORAGE_BUFFER_BIT, nullptr, 0, out_bytes));
            owned.push_back(make(VK_BUFFER_USAGE_UNIFORM_BUFFER_BIT, grid_bytes.data(), grid_bytes.size(),
                                 grid_bytes.size()));
            // binding -> buffer and range: OUT's range is exactly the output, since the shader bounds every
            // invocation by arrayLength on it
            const Buffer* at[7] = {&owned[0], &tables, &owned[1], &owned[2], &owned[3], &owned[4], &owned[5]};
            VkDeviceSize range[7] = {r.params.size(), tables.size, at[2]->size, at[3]->size, at[4]->size, out_bytes,
                                     grid_bytes.size()};

            VkDescriptorPoolSize sizes[2] = {{VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER, 2},
                                             {VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 5}};
            auto dpi = info<VkDescriptorPoolCreateInfo>(VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO);
            dpi.maxSets = 1;
            dpi.poolSizeCount = 2;
            dpi.pPoolSizes = sizes;
            check(vkCreateDescriptorPool(dev, &dpi, nullptr, &dpool), "vkCreateDescriptorPool");
            auto dsa = info<VkDescriptorSetAllocateInfo>(VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO);
            dsa.descriptorPool = dpool;
            dsa.descriptorSetCount = 1;
            dsa.pSetLayouts = &set_layout;
            VkDescriptorSet set = VK_NULL_HANDLE;
            check(vkAllocateDescriptorSets(dev, &dsa, &set), "vkAllocateDescriptorSets");
            VkDescriptorBufferInfo infos[7];
            VkWriteDescriptorSet writes[7];
            for (uint32_t i = 0; i < 7; ++i) {
                infos[i] = {at[i]->buffer, 0, range[i]};
                writes[i] = info<VkWriteDescriptorSet>(VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET);
                writes[i].dstSet = set;
                writes[i].dstBinding = i;
                writes[i].descriptorCount = 1;
                writes[i].descriptorType = kTypes[i];
                writes[i].pBufferInfo = &infos[i];
            }
            vkUpdateDescriptorSets(dev, 7, writes, 0, nullptr);

            auto cba = info<VkCommandBufferAllocateInfo>(VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO);
            cba.commandPool = pool;
            cba.level = VK_COMMAND_BUFFER_LEVEL_PRIMARY;
            cba.commandBufferCount = 1;
            check(vkAllocateCommandBuffers(dev, &cba, &cmd), "vkAllocateCommandBuffers");
            auto begin = info<VkCommandBufferBeginInfo>(VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO);
            begin.flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT;
            check(vkBeginCommandBuffer(cmd, &begin), "vkBeginCommandBuffer");
            vkCmdBindPipeline(cmd, VK_PIPELINE_BIND_POINT_COMPUTE, pipelines.at(r.entry));
            vkCmdBindDescriptorSets(cmd, VK_PIPELINE_BIND_POINT_COMPUTE, layout, 0, 1, &set, 0, nullptr);
            vkCmdDispatch(cmd, r.gx, r.gy, 1);
            // the shader's writes made visible to the host's read of binding 5, as GL's glMemoryBarrier is
            auto barrier = info<VkMemoryBarrier>(VK_STRUCTURE_TYPE_MEMORY_BARRIER);
            barrier.srcAccessMask = VK_ACCESS_SHADER_WRITE_BIT;
            barrier.dstAccessMask = VK_ACCESS_HOST_READ_BIT;
            vkCmdPipelineBarrier(cmd, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, VK_PIPELINE_STAGE_HOST_BIT, 0, 1, &barrier,
                                 0, nullptr, 0, nullptr);
            check(vkEndCommandBuffer(cmd), "vkEndCommandBuffer");

            auto fci = info<VkFenceCreateInfo>(VK_STRUCTURE_TYPE_FENCE_CREATE_INFO);
            check(vkCreateFence(dev, &fci, nullptr, &fence), "vkCreateFence");
            auto submit = info<VkSubmitInfo>(VK_STRUCTURE_TYPE_SUBMIT_INFO);
            submit.commandBufferCount = 1;
            submit.pCommandBuffers = &cmd;
            check(vkQueueSubmit(queue, 1, &submit, fence), "vkQueueSubmit");
            // a failed wait would read the output back before the device wrote it
            check(vkWaitForFences(dev, 1, &fence, VK_TRUE, UINT64_MAX), "vkWaitForFences");

            std::vector<float> values(out_bytes / 4);
            void* p = nullptr;
            check(vkMapMemory(dev, owned[4].memory, 0, VK_WHOLE_SIZE, 0, &p), "vkMapMemory (output)");
            std::memcpy(values.data(), p, out_bytes);
            vkUnmapMemory(dev, owned[4].memory);
            cleanup();
            return values;
        } catch (...) {
            cleanup();
            throw;
        }
    }
};

std::unique_ptr<Backend> open_backend(const std::string& api) {
    if (api == "vulkan") return std::make_unique<Vulkan>();
    throw std::runtime_error("unknown --api " + api + ": vulkan");
}

}  // namespace

int main(int argc, char** argv) { return frames::serve(argc, argv, open_backend); }
