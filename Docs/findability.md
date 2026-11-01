# Findability: who looks for HogNoise, and where they must find it

**Status:** Living. The owner, 2026-11-01: *"why would someone else search for this, need it or want it? make that durable."*
Updated in the same pull request as any change that adds a feature, removes one, or changes what the README claims.

## Who looks for it, and why

| Who | What they need | What they type |
| --- | --- | --- |
| Python developers making terrain, heightmaps, worlds or levels | fast 2D and 3D noise over numpy arrays, with fractals and warping | python perlin noise, python simplex noise, numpy noise, procedural terrain python, heightmap python |
| Game developers who know FastNoiseLite from Godot 4, Unity or C++ | the same algorithms and parameters in Python, for tools, baking or prototyping | fastnoiselite python, fastnoise python, opensimplex2 python |
| People on `pyfastnoisesimd` or another stalled wrapper | something that installs on Python 3.11 to 3.13, with FastNoiseSIMD's own noise so old seeds reproduce | pyfastnoisesimd alternative, pyfastnoisesimd python 3.12, fastnoisesimd python |
| Technical artists in a DCC host (Maya first) | noise that installs with numpy alone, no compiler, on the host's numpy (Maya 2026 ships 1.26) | maya python noise, numpy perlin noise no compiler |
| Texture, generative-art and synthetic-data work | seeded, repeatable noise: same parameters, same array | cellular noise python, worley noise python, voronoi noise numpy, domain warp python, fbm noise python |
| Anyone who needs to trust the numbers | proof the port matches the originals | fastnoiselite port, noise test vectors |

Only the last row is unusual. The other rows have alternatives; what HogNoise adds for them is the evidence: the comparison
table, numba and numpy agreeing bit for bit, and the seeds of both FastNoiseLite and FastNoiseSIMD.

## The surfaces, and what each one says now

| Surface | Where it is set | Now |
| --- | --- | --- |
| The README's first paragraph and *Who it's for* | [README.md](../README.md) | the people above, in prose; no keyword list |
| Image alt text | the README's `<img>` tags | names the noise types each picture shows |
| The GitHub description | `gh repo edit --description` | Procedural noise for Python: Perlin, OpenSimplex2, cellular (Worley) and domain warp. Every FastNoiseLite and FastNoiseSIMD algorithm, fast with numba, exact with numpy, checked against the originals |
| The GitHub topics | `gh repo edit --add-topic` | procedural-noise, procedural-generation, perlin-noise, simplex-noise, opensimplex, fastnoise, fastnoiselite, cellular-noise, worley-noise, voronoi, domain-warping, fractal-noise, terrain-generation, heightmap, gamedev, numpy, numba, python |
| The package metadata | `pyproject.toml`: `description`, `keywords`, `classifiers` | the same words; it becomes the PyPI page when the package is released |
| The index for AI tools | [llms.txt](../llms.txt) | one summary, current, plus the evidence links |

## Rules

- **A term names something shipped.** No `gpu`, `wgsl`, `shader`, `4d` or `fastnoise2` term goes on any surface until it
  ships with vectors behind it, as [the definition of done](standards/definition-of-done-project.md) already requires of
  claims. When the GPU rung lands, `wgsl`, `webgpu` and `gpu` join the topics and keywords in that pull request.
- **Prose, not a keyword list.** A search engine and a reader both reward a paragraph that answers *why would I want this*;
  neither rewards a pile of tags in the README.
- **Every surface says the same thing.** When one changes, check the others in the same pull request. The GitHub
  description and topics live outside the repository, so this table is their record; change the table when you change them.
- **Name alternatives fairly.** FastNoise2 is the answer for 4D, a node editor or C++ speed, and the README says so.
