# My TikZ Figures

A collection of 520 standalone TikZ and PGFPlots figures extracted from various academic and professional projects. Every file compiles to PDF independently.

## Directory Structure

| Folder | Figures | Description |
|--------|---------|-------------|
| `aerospace/` | 53 | Wing planforms, fuselage geometry, mission profiles |
| `architecture_diagrams/` | 64 | System pipelines, block diagrams, network architectures |
| `branding/` | 28 | Logos, marketing graphics, flyers |
| `computer_vision/` | 82 | Optical flow, depth estimation, image registration |
| `controls/` | 8 | Step response, Bode plots, PID, root locus |
| `data_visualization/` | 183 | PGFPlots charts, training curves, statistical plots |
| `math/` | 2 | Vector diagrams, calculus illustrations |
| `organizational/` | 11 | Org charts, timelines, financial flow diagrams |
| `radar/` | 32 | Echo trails, CFAR detection, radar signal processing |
| `reinforcement_learning/` | 51 | Q-learning, MDP diagrams, policy visualizations |
| `sensor_systems/` | 6 | IR-RGB calibration, camera pipelines, hardware diagrams |
| `data/` | --- | CSV files referenced by data-driven plots |
| `scripts/` | --- | Extraction and compilation utilities |

## Requirements

- A TeX distribution with `pdflatex` (e.g., [TeX Live](https://tug.org/texlive/) or [MacTeX](https://tug.org/mactex/))
- Core LaTeX packages (included with most full TeX distributions):
  - `tikz` and TikZ libraries (arrows.meta, calc, positioning, decorations, patterns, etc.)
  - `pgfplots` (v1.18+) for data-driven plots
  - `standalone` document class
- A few figures require `xelatex` instead of `pdflatex` (marked with `% Requires: xelatex` in the file header)

## Compilation

Each file is self-contained and compiles independently:

```bash
pdflatex <filename>.tex
```

To compile all figures at once:

```bash
bash scripts/compile_all.sh
```

Results are logged to `scripts/compile_log.txt`.

## License

MIT

## Author

J.C. Vaught
