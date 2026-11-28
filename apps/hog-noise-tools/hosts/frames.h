// HogNoise tools: what every C++ host harness shares, written from hog_noise/shaders/README.md alone. The frames, the
// entry points' shapes, the refusals and the loop; each harness adds one back end per graphics API and its main.
//
// A persistent process: Python (hog_noise_tools.hosts.harness) starts it once, sends the tables and the five entry
// points' programs, then one request per dispatch on standard input, and reads each reply on standard output before
// it sends the next. It reads no file: every byte it binds came through Python, which hashed the shader and the tables
// against the manifest. The frames are little-endian; a blob is a u32 length and that many bytes.
//
//   init     "HNH1", blob tables, u32 count (5), count x (blob name, blob program)
//   request  u32 entry, u32 n, u32 width, u32 groups_x, u32 groups_y, blob params (112 bytes), blob grid (empty: none;
//            else 48 bytes), u32 axes (at most 3), axes x blob (n float32)
//   reply    u32 status, blob: 0 the output (n * width float32) or the target line after init; 1 an error, its message;
//            2 (init only) no device here, its message
//
// A request the bindings cannot hold (an axis not n floats, an entry past the five, a width, axis count or Grid its
// entry point does not take) is refused with status 1 and the harness reads on. A frame it cannot read (input ending
// inside one, a blob past 1 GiB, more than 3 axes) leaves the stream unreadable: status 1, then it ends. Standard input
// closing between frames ends it with 0.

#pragma once

#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#endif

#include <cstdint>
#include <cstdio>
#include <cstring>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

namespace frames {

using Bytes = std::vector<uint8_t>;

struct Eof {};

// the README's five entry points: an init frame must carry exactly this many programs
constexpr uint32_t kEntryPoints = 5;
// the most one blob may hold: past it the length is taken as a broken stream, not an allocation to try
constexpr uint32_t kMaxBlob = 1u << 30;
// the README's uniforms: Params is 112 bytes, Grid 48
constexpr size_t kParamsBytes = 112, kGridBytes = 48;

// the frames themselves are broken: the stream cannot be read past this point, so the harness replies and ends
struct FrameError : std::runtime_error {
    using std::runtime_error::runtime_error;
};

// a device or adapter missing: the host is unavailable here, which Python turns into a skip unless it is required
struct Unavailable : std::runtime_error {
    using std::runtime_error::runtime_error;
};

inline void read_exact(void* into, size_t n, bool eof_ok = false) {
    size_t got = std::fread(into, 1, n, stdin);
    if (got == 0 && eof_ok) throw Eof{};
    if (got != n) throw FrameError("standard input ended inside a frame");
}

inline uint32_t read_u32(bool eof_ok = false) {
    uint32_t v = 0;
    read_exact(&v, 4, eof_ok);
    return v;
}

inline Bytes read_blob() {
    uint32_t len = read_u32();
    if (len > kMaxBlob)
        throw FrameError("a blob of " + std::to_string(len) + " bytes, past the " + std::to_string(kMaxBlob) +
                         " a frame may hold");
    Bytes b(len);
    if (!b.empty()) read_exact(b.data(), b.size());
    return b;
}

inline void reply(uint32_t status, const void* data, size_t n) {
    uint32_t len = static_cast<uint32_t>(n);
    std::fwrite(&status, 4, 1, stdout);
    std::fwrite(&len, 4, 1, stdout);
    if (n) std::fwrite(data, 1, n, stdout);
    std::fflush(stdout);
}

inline void reply_text(uint32_t status, const std::string& text) { reply(status, text.data(), text.size()); }

// One request's inputs, as the README's bindings: 0 Params, 2-4 the coordinates, 6 Grid.
struct Request {
    uint32_t entry, n, width, gx, gy;
    Bytes params, grid;
    std::vector<Bytes> axes;
};

// What one entry point reads and writes, from the README's *Output* and its bindings table: the floats per point it
// writes to binding 5, the coordinates it reads from bindings 2-4, and whether it reads Grid (binding 6).
struct Shape {
    const char* name;
    uint32_t width, axes;
    bool grid;
};

constexpr Shape kShapes[kEntryPoints] = {
    {"sample_points_3d", 1, 3, false}, {"sample_points_2d", 1, 2, false}, {"sample_grid", 1, 0, true},
    {"warp_points_3d", 3, 3, false},   {"warp_points_2d", 2, 2, false},
};

// The shape of an init frame's program, by its name: a name the README does not list is refused at init.
inline Shape shape_of(const std::string& name) {
    for (const Shape& s : kShapes)
        if (name == s.name) return s;
    throw std::runtime_error("the init frame names \"" + name + "\", not one of the README's entry points");
}

// A request the README's bindings cannot hold is refused before it reaches the device: an axis shorter than n
// would read zeros past its end, and a width, axis count or Grid its entry point does not take would leave the
// output partly unwritten or the coordinates zero, each returning output that looks valid.
inline void validate(const Request& r, const std::vector<Shape>& shapes) {
    using std::to_string;
    if (r.entry >= shapes.size())
        throw std::runtime_error("entry " + to_string(r.entry) + " is not one of the " + to_string(shapes.size()));
    const Shape& s = shapes[r.entry];
    if (r.n == 0) throw std::runtime_error("a request for 0 points");
    // The README's *Dispatch*, exactly: fewer workgroups would leave points unwritten, more than 65,535 along x is
    // past what one dimension allows, and either would come back looking like a result.
    const uint32_t groups = r.n / 64 + (r.n % 64 != 0);
    const uint32_t want_gx = groups < 65535 ? groups : 65535, want_gy = groups / 65535 + (groups % 65535 != 0);
    if (r.gx != want_gx || r.gy != want_gy)
        throw std::runtime_error("workgroups " + to_string(r.gx) + " x " + to_string(r.gy) + " for " +
                                 to_string(r.n) + " points, not the README's " + to_string(want_gx) + " x " +
                                 to_string(want_gy));
    if (r.width != s.width)
        throw std::runtime_error(std::string(s.name) + " writes " + to_string(s.width) + " floats per point, not " +
                                 to_string(r.width));
    if (r.params.size() != kParamsBytes)
        throw std::runtime_error("Params is " + to_string(r.params.size()) + " bytes, not " + to_string(kParamsBytes));
    if (r.grid.size() != (s.grid ? kGridBytes : 0))
        throw std::runtime_error(std::string(s.name) + (s.grid ? " reads a 48-byte Grid" : " reads no Grid") +
                                 ", and the request sent " + to_string(r.grid.size()) + " bytes");
    if (r.axes.size() != s.axes)
        throw std::runtime_error(std::string(s.name) + " reads " + to_string(s.axes) + " axes, not " +
                                 to_string(r.axes.size()));
    for (size_t i = 0; i < r.axes.size(); ++i)
        if (r.axes[i].size() != size_t(r.n) * 4)
            throw std::runtime_error("axis " + to_string(i) + " holds " + to_string(r.axes[i].size()) +
                                     " bytes, not " + to_string(size_t(r.n) * 4) + " for " + to_string(r.n) +
                                     " points");
    if (size_t(r.n) * r.width * 4 > UINT32_MAX)
        throw std::runtime_error("an output of " + to_string(size_t(r.n) * r.width * 4) + " bytes, past 4 GiB");
}

struct Backend {
    virtual ~Backend() = default;
    virtual void load(const Bytes& tables, const std::vector<Bytes>& programs) = 0;
    virtual std::vector<float> run(const Request& r) = 0;
    std::string target;
    std::vector<std::string> names;  // the entry points, in the init frame's order: named in a refusal
    std::vector<Shape> shapes;       // and what each reads and writes, in the same order
};

inline size_t round_up(size_t n, size_t to) { return (n + to - 1) / to * to; }

// The harness's whole life: the init frame, then one reply per request until standard input closes. ``open`` makes
// the back end ``--api`` names, after the init frame is read and its names checked; it throws Unavailable for no
// device. Returns the exit code.
template <typename Open>
int serve(int argc, char** argv, Open open) {
#ifdef _WIN32
    _setmode(_fileno(stdin), _O_BINARY);
    _setmode(_fileno(stdout), _O_BINARY);
#endif
    std::string api = argc == 3 && std::string(argv[1]) == "--api" ? argv[2] : "";

    std::unique_ptr<Backend> backend;
    try {
        char magic[4];
        read_exact(magic, 4);
        if (std::memcmp(magic, "HNH1", 4) != 0) throw std::runtime_error("not an HNH1 init frame");
        Bytes tables = read_blob();
        std::vector<Bytes> blobs;
        std::vector<std::string> names;
        std::vector<Shape> shapes;
        uint32_t count = read_u32();
        if (count != kEntryPoints)
            throw std::runtime_error("the init frame has " + std::to_string(count) + " programs, not " +
                                     std::to_string(kEntryPoints));
        for (uint32_t i = 0; i < count; ++i) {
            Bytes name = read_blob();
            names.emplace_back(name.begin(), name.end());
            blobs.push_back(read_blob());
        }
        for (const std::string& name : names) shapes.push_back(shape_of(name));
        backend = open(api);
        backend->names = names;
        backend->shapes = shapes;
        backend->load(tables, blobs);
        reply_text(0, backend->target);
    } catch (const Unavailable& e) {
        reply_text(2, e.what());
        return 2;
    } catch (const std::exception& e) {
        reply_text(1, e.what());
        return 1;
    }

    for (;;) {
        Request r;
        try {
            r.entry = read_u32(true);
            r.n = read_u32();
            r.width = read_u32();
            r.gx = read_u32();
            r.gy = read_u32();
            r.params = read_blob();
            r.grid = read_blob();
            uint32_t count = read_u32();
            if (count > 3) throw FrameError(std::to_string(count) + " axes, not at most 3");
            for (uint32_t i = 0; i < count; ++i) r.axes.push_back(read_blob());
        } catch (const Eof&) {
            return 0;  // standard input closed between frames: the signal to end
        } catch (const std::exception& e) {
            reply_text(1, e.what());  // the stream cannot be read past a broken frame
            return 1;
        }
        try {
            validate(r, backend->shapes);
            std::vector<float> values = backend->run(r);
            reply(0, values.data(), values.size() * 4);
        } catch (const std::exception& e) {
            reply_text(1, e.what());
        }
    }
}

}  // namespace frames
