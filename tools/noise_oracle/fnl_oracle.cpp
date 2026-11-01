// LargeWorlds: the FastNoiseLite oracle for what pyfastnoiselite does not expose (domain warp).
// Package: tools/noise_oracle
//
// pyfastnoiselite 0.0.7 binds GetNoise only; FastNoiseLite::DomainWarp is not reachable from Python,
// so the Phase B domain-warp vectors come from this harness over the vendored reference header
// (FastNoiseLite.h, MIT, Jordan Peck and contributors; version 1.1.1, verbatim).
//
// Usage:
//   fnl_oracle <mode> <in.f32> <out.f32> <seed> <frequency> <noise_type> <fractal_type> <octaves>
//              <lacunarity> <gain> <weighted> <pingpong> <rotation_3d> <warp_type> <warp_amp>
//
//   mode       warp2 | warp3 | noise2 | noise3
//   in.f32     little-endian float32, N x dims (dims 2 or 3), row-major
//   out.f32    warp*: N x dims warped coordinates; noise*: N values
//   enums      FastNoiseLite's integer values (NoiseType, FractalType, RotationType3D, DomainWarpType)
//
// Everything runs in float, as pyfastnoiselite's gen_from_coords does, so the two oracles agree.
// Built by build.bat with MSVC; the executable is not committed.

#include "FastNoiseLite.h"

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

static std::vector<float> read_f32(const char* path) {
    std::vector<float> data;
    FILE* f = std::fopen(path, "rb");
    if (!f) {
        std::fprintf(stderr, "cannot open %s\n", path);
        std::exit(2);
    }
    float buf[4096];
    size_t n;
    while ((n = std::fread(buf, sizeof(float), 4096, f)) > 0) {
        data.insert(data.end(), buf, buf + n);
    }
    std::fclose(f);
    return data;
}

static void write_f32(const char* path, const std::vector<float>& data) {
    FILE* f = std::fopen(path, "wb");
    if (!f) {
        std::fprintf(stderr, "cannot open %s for writing\n", path);
        std::exit(2);
    }
    std::fwrite(data.data(), sizeof(float), data.size(), f);
    std::fclose(f);
}

int main(int argc, char** argv) {
    if (argc != 16) {
        std::fprintf(stderr, "expected 15 arguments, got %d; see the header comment\n", argc - 1);
        return 1;
    }
    const std::string mode = argv[1];
    const char* in_path = argv[2];
    const char* out_path = argv[3];
    const int seed = std::atoi(argv[4]);
    const float frequency = static_cast<float>(std::atof(argv[5]));
    const int noise_type = std::atoi(argv[6]);
    const int fractal_type = std::atoi(argv[7]);
    const int octaves = std::atoi(argv[8]);
    const float lacunarity = static_cast<float>(std::atof(argv[9]));
    const float gain = static_cast<float>(std::atof(argv[10]));
    const float weighted = static_cast<float>(std::atof(argv[11]));
    const float pingpong = static_cast<float>(std::atof(argv[12]));
    const int rotation = std::atoi(argv[13]);
    const int warp_type = std::atoi(argv[14]);
    const float warp_amp = static_cast<float>(std::atof(argv[15]));

    FastNoiseLite noise(seed);
    noise.SetFrequency(frequency);
    noise.SetNoiseType(static_cast<FastNoiseLite::NoiseType>(noise_type));
    noise.SetFractalType(static_cast<FastNoiseLite::FractalType>(fractal_type));
    noise.SetFractalOctaves(octaves);
    noise.SetFractalLacunarity(lacunarity);
    noise.SetFractalGain(gain);
    noise.SetFractalWeightedStrength(weighted);
    noise.SetFractalPingPongStrength(pingpong);
    noise.SetRotationType3D(static_cast<FastNoiseLite::RotationType3D>(rotation));
    noise.SetDomainWarpType(static_cast<FastNoiseLite::DomainWarpType>(warp_type));
    noise.SetDomainWarpAmp(warp_amp);

    const std::vector<float> in = read_f32(in_path);
    std::vector<float> out;

    if (mode == "warp2") {
        out = in;
        for (size_t i = 0; i + 1 < out.size(); i += 2) {
            noise.DomainWarp(out[i], out[i + 1]);
        }
    } else if (mode == "warp3") {
        out = in;
        for (size_t i = 0; i + 2 < out.size(); i += 3) {
            noise.DomainWarp(out[i], out[i + 1], out[i + 2]);
        }
    } else if (mode == "noise2") {
        out.reserve(in.size() / 2);
        for (size_t i = 0; i + 1 < in.size(); i += 2) {
            out.push_back(noise.GetNoise(in[i], in[i + 1]));
        }
    } else if (mode == "noise3") {
        out.reserve(in.size() / 3);
        for (size_t i = 0; i + 2 < in.size(); i += 3) {
            out.push_back(noise.GetNoise(in[i], in[i + 1], in[i + 2]));
        }
    } else {
        std::fprintf(stderr, "unknown mode %s\n", mode.c_str());
        return 1;
    }
    write_f32(out_path, out);
    return 0;
}
