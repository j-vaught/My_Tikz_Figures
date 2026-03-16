#!/usr/bin/env python3
"""
Extract all TikZ/PGFPlots figures from a source directory into standalone .tex files.

Set TIKZ_EXTRACT_ROOT to the directory to scan (defaults to two levels above this script).
Set TIKZ_EXTRACT_OUTPUT to the output directory (defaults to the repo root).

Categories:
  A: Already standalone (has \\documentclass{standalone})  -> copy with minor fixes
  B: Fragment (no \\documentclass, has tikzpicture/axis)   -> wrap in standalone shell
  C: Embedded in larger doc (article/beamer/report)       -> extract each tikzpicture
"""

import os
import re
import hashlib
import shutil
import json
from pathlib import Path
from collections import defaultdict

ROOT = Path(os.environ.get("TIKZ_EXTRACT_ROOT", Path(__file__).resolve().parent.parent.parent))
OUTPUT_DIR = Path(os.environ.get("TIKZ_EXTRACT_OUTPUT", Path(__file__).resolve().parent.parent))
STAGING = OUTPUT_DIR / "_staging"
DATA_DIR = OUTPUT_DIR / "data"

# Directories to skip
SKIP_DIRS = {
    "My_Tikz_Figures", ".git", "__pycache__", "node_modules",
    ".venv", "venv", "env", ".tox", "build", "dist",
    "tikzgif",  # skip animations per user request
}

# Topic classification rules: (path_pattern, topic_folder)
TOPIC_RULES = [
    # Aerospace
    (r"AESP[_\s]?466|EMCH[_\s]?721|aerospace|wing_planform|fuselage|mission_geometry", "aerospace"),
    # Architecture diagrams
    (r"architecture|pipeline|block_diagram|system_diagram|network_arch|flowchart", "architecture_diagrams"),
    # Branding
    (r"CommonSense|Daily_Gamecock|StudentGovernment|logo|flyer|campaign|ads/|branding", "branding"),
    # Computer vision
    (r"ML_overlay|CSCE[_\s]?763|optical_flow|RAFT|depth|registration|computer_vision|cv_", "computer_vision"),
    # Controls
    (r"EMCH[_\s]?367|bode|step_response|root_locus|pid|controls|transfer_function", "controls"),
    # Data visualization
    (r"data_exploration|training_curve|pgfplots|data_vis|statistics|bar_chart|scatter", "data_visualization"),
    # Math
    (r"MATH[_\s]?\d|vector_diagram|calculus|parametric|geometry|trig", "math"),
    # Organizational
    (r"UofSC_Finance|org_chart|timeline|finance|lobbying|organizational", "organizational"),
    # Radar
    (r"RADAR|radar|echo_trail|CFAR|xband", "radar"),
    # Reinforcement learning
    (r"CSCE[_\s]?775|reinforcement|q.?learning|MDP|policy|bellman|markov", "reinforcement_learning"),
    # Sensor systems
    (r"ir.?rgb|calibration|FLIR|camera|hardware|sensor|infrared|thermal", "sensor_systems"),
]

# Default topic if no rule matches
DEFAULT_TOPIC = "data_visualization"


def classify_topic(filepath: str, content: str) -> str:
    """Determine which topic folder a file belongs in based on path and content."""
    combined = filepath + "\n" + content[:2000]
    for pattern, topic in TOPIC_RULES:
        if re.search(pattern, combined, re.IGNORECASE):
            return topic
    return DEFAULT_TOPIC


def get_file_hash(content: str) -> str:
    """Hash file content for deduplication."""
    # Normalize whitespace for comparison
    normalized = re.sub(r'\s+', ' ', content.strip())
    return hashlib.md5(normalized.encode()).hexdigest()


def extract_braced_block(text: str, start_pos: int) -> str:
    """Extract a complete {...} block starting at start_pos (which should point to '{').
    Returns the full block including braces, handling nested braces."""
    if start_pos >= len(text) or text[start_pos] != '{':
        return ''
    depth = 0
    pos = start_pos
    while pos < len(text):
        if text[pos] == '{':
            depth += 1
        elif text[pos] == '}':
            depth -= 1
            if depth == 0:
                return text[start_pos:pos+1]
        pos += 1
    return text[start_pos:]  # unclosed, return what we have


def extract_command_with_braces(text: str, command: str) -> list:
    """Find all occurrences of \\command{...} with proper brace matching."""
    results = []
    pattern = re.escape(command)
    for m in re.finditer(pattern, text):
        # Find the opening brace after the command
        pos = m.end()
        # Skip whitespace/newlines
        while pos < len(text) and text[pos] in ' \t\n\r':
            pos += 1
        if pos < len(text) and text[pos] == '{':
            block = extract_braced_block(text, pos)
            results.append(command + block)
    return results


def extract_preamble(content: str) -> dict:
    """Extract useful preamble elements from a document."""
    preamble = {}

    # Find everything between \documentclass and \begin{document}
    m = re.search(r'\\documentclass.*?\n(.*?)\\begin\{document\}', content, re.DOTALL)
    if not m:
        return preamble

    pream_text = m.group(1)

    # Extract packages
    packages = re.findall(r'(\\usepackage(?:\[.*?\])?\{.*?\})', pream_text)
    preamble['packages'] = packages

    # Extract tikz libraries
    tikzlibs = re.findall(r'(\\usetikzlibrary\{.*?\})', pream_text, re.DOTALL)
    preamble['tikzlibs'] = tikzlibs

    # Extract pgfplots libraries
    pgflibs = re.findall(r'(\\usepgfplotslibrary\{.*?\})', pream_text, re.DOTALL)
    preamble['pgflibs'] = pgflibs

    # Extract pgfplotsset with proper brace matching
    pgfsets = extract_command_with_braces(pream_text, r'\pgfplotsset')
    preamble['pgfsets'] = pgfsets

    # Extract color definitions
    colors = re.findall(r'(\\definecolor\{.*?\}\{.*?\}\{.*?\})', pream_text)
    preamble['colors'] = colors

    # Extract tikzset with proper brace matching
    tikzsets = extract_command_with_braces(pream_text, r'\tikzset')
    preamble['tikzsets'] = tikzsets

    # Extract newcommands - only TikZ/math related ones
    # Skip document-level commands that break standalone
    skip_cmd_names = {
        r'\headrulewidth', r'\footrulewidth', r'\question',
        r'\questionpart', r'\maketitle', r'\tableofcontents',
        r'\familydefault', r'\thesection', r'\thesubsection',
        r'\abstractname', r'\contentsname', r'\refname',
        r'\bibname', r'\indexname', r'\figurename',
        r'\tablename', r'\appendixname', r'\proofname',
        r'\headrule', r'\footrule', r'\chaptermark',
        r'\sectionmark', r'\subsectionmark',
    }
    newcmds = []
    for m2 in re.finditer(r'\\(newcommand|renewcommand)\*?', pream_text):
        cmd_start = m2.start()
        pos = m2.end()
        while pos < len(pream_text) and pream_text[pos] in ' \t\n\r':
            pos += 1
        if pos < len(pream_text) and pream_text[pos] == '{':
            name_block = extract_braced_block(pream_text, pos)
            # Check if this is a command we should skip
            cmd_name = name_block[1:-1]  # strip braces
            if cmd_name in skip_cmd_names:
                continue
            pos += len(name_block)
            while pos < len(pream_text) and pream_text[pos] in ' \t\n\r':
                pos += 1
            opt_arg = ''
            if pos < len(pream_text) and pream_text[pos] == '[':
                end_bracket = pream_text.find(']', pos)
                if end_bracket != -1:
                    opt_arg = pream_text[pos:end_bracket+1]
                    pos = end_bracket + 1
            while pos < len(pream_text) and pream_text[pos] in ' \t\n\r':
                pos += 1
            if pos < len(pream_text) and pream_text[pos] == '{':
                body = extract_braced_block(pream_text, pos)
                full_cmd = pream_text[cmd_start:m2.end()] + name_block + opt_arg + body
                newcmds.append(full_cmd)
    preamble['newcmds'] = newcmds

    # Extract \def commands
    defs = []
    for m2 in re.finditer(r'\\def\\[a-zA-Z]+', pream_text):
        pos = m2.end()
        # Skip optional parameter pattern like #1#2
        while pos < len(pream_text) and pream_text[pos] in ' \t\n\r#0123456789':
            pos += 1
        if pos < len(pream_text) and pream_text[pos] == '{':
            body = extract_braced_block(pream_text, pos)
            defs.append(pream_text[m2.start():pos] + body)
    preamble['defs'] = defs

    # Extract pgfmathsetmacro
    macros = re.findall(r'(\\pgfmathsetmacro\{.*?\}\{.*?\})', pream_text)
    preamble['macros'] = macros

    # Extract newtcolorbox definitions
    tcolorboxes = []
    for m2 in re.finditer(r'\\newtcolorbox', pream_text):
        pos = m2.end()
        while pos < len(pream_text) and pream_text[pos] in ' \t\n\r':
            pos += 1
        if pos < len(pream_text) and pream_text[pos] == '{':
            name_block = extract_braced_block(pream_text, pos)
            pos += len(name_block)
            # Optional args
            while pos < len(pream_text) and pream_text[pos] in ' \t\n\r':
                pos += 1
            opt_arg = ''
            if pos < len(pream_text) and pream_text[pos] == '[':
                end_bracket = pream_text.find(']', pos)
                if end_bracket != -1:
                    opt_arg = pream_text[pos:end_bracket+1]
                    pos = end_bracket + 1
            while pos < len(pream_text) and pream_text[pos] in ' \t\n\r':
                pos += 1
            if pos < len(pream_text) and pream_text[pos] == '{':
                body = extract_braced_block(pream_text, pos)
                tcolorboxes.append(pream_text[m2.start():pos] + body)
    preamble['tcolorboxes'] = tcolorboxes

    # Extract newenvironment definitions
    newenvs = []
    for m2 in re.finditer(r'\\newenvironment', pream_text):
        cmd_start = m2.start()
        pos = m2.end()
        while pos < len(pream_text) and pream_text[pos] in ' \t\n\r':
            pos += 1
        if pos < len(pream_text) and pream_text[pos] == '{':
            name_block = extract_braced_block(pream_text, pos)
            pos += len(name_block)
            # Optional args
            while pos < len(pream_text) and pream_text[pos] in ' \t\n\r':
                pos += 1
            opt_arg = ''
            if pos < len(pream_text) and pream_text[pos] == '[':
                end_bracket = pream_text.find(']', pos)
                if end_bracket != -1:
                    opt_arg = pream_text[pos:end_bracket+1]
                    pos = end_bracket + 1
            # Begin block
            while pos < len(pream_text) and pream_text[pos] in ' \t\n\r':
                pos += 1
            if pos < len(pream_text) and pream_text[pos] == '{':
                begin_body = extract_braced_block(pream_text, pos)
                pos += len(begin_body)
                # End block
                while pos < len(pream_text) and pream_text[pos] in ' \t\n\r':
                    pos += 1
                if pos < len(pream_text) and pream_text[pos] == '{':
                    end_body = extract_braced_block(pream_text, pos)
                    newenvs.append(pream_text[cmd_start:m2.end()] + name_block + opt_arg + begin_body + end_body)
    preamble['newenvs'] = newenvs

    # Check for fontspec (xelatex requirement)
    preamble['needs_xelatex'] = bool(re.search(r'\\usepackage\{fontspec\}', pream_text))

    # Check for setsansfont/setmainfont with paths (need to fix relative paths)
    font_cmds = []
    for fm in re.finditer(r'(\\set(?:sans|main|mono)font)', pream_text):
        pos = fm.end()
        # Capture everything up to the next blank line or next top-level command
        end = pream_text.find('\n\n', pos)
        if end == -1:
            end = len(pream_text)
        font_cmds.append(pream_text[fm.start():end].strip())
    preamble['font_cmds'] = font_cmds

    return preamble


def find_tikzpictures(content: str) -> list:
    """Find all tikzpicture environments in document body, handling nesting."""
    body_match = re.search(r'\\begin\{document\}(.*?)\\end\{document\}', content, re.DOTALL)
    if not body_match:
        return []

    body = body_match.group(1)
    figures = []

    # Find tikzpicture environments with depth counting
    pattern = r'\\begin\{tikzpicture\}'
    for m in re.finditer(pattern, body):
        start = m.start()
        depth = 1
        pos = m.end()
        while depth > 0 and pos < len(body):
            next_begin = body.find(r'\begin{tikzpicture}', pos)
            next_end = body.find(r'\end{tikzpicture}', pos)
            if next_end == -1:
                break
            if next_begin != -1 and next_begin < next_end:
                depth += 1
                pos = next_begin + len(r'\begin{tikzpicture}')
            else:
                depth -= 1
                if depth == 0:
                    end = next_end + len(r'\end{tikzpicture}')
                    tikz_code = body[start:end]

                    # Look for caption in surrounding figure environment
                    caption = ""
                    # Search backwards for \begin{figure}
                    pre_context = body[max(0, start-500):start]
                    if r'\begin{figure}' in pre_context or r'\begin{center}' in pre_context:
                        # Search forward for caption
                        post_context = body[end:end+500]
                        cap_match = re.search(r'\\caption\{(.*?)\}', post_context, re.DOTALL)
                        if cap_match:
                            caption = cap_match.group(1).strip()

                    # Capture preceding pgfmathsetmacro and tikzset
                    pre_defs = []
                    pre_text = body[max(0, start-2000):start]
                    # Get pgfmathsetmacro lines just before
                    for pm in re.finditer(r'(\\pgfmathsetmacro\{.*?\}\{.*?\})', pre_text):
                        pre_defs.append(pm.group(1))
                    # Get tikzset just before (with proper brace matching)
                    pre_defs.extend(extract_command_with_braces(pre_text, r'\tikzset'))

                    figures.append({
                        'code': tikz_code,
                        'caption': caption,
                        'pre_defs': pre_defs,
                    })
                    break
                else:
                    pos = next_end + len(r'\end{tikzpicture}')

    return figures


def find_axis_envs(content: str) -> list:
    """Find standalone axis environments (not inside tikzpicture)."""
    body_match = re.search(r'\\begin\{document\}(.*?)\\end\{document\}', content, re.DOTALL)
    if not body_match:
        return []

    body = body_match.group(1)
    figures = []

    for m in re.finditer(r'\\begin\{axis\}', body):
        start = m.start()
        # Check if this axis is inside a tikzpicture we already found
        pre = body[:start]
        tikz_depth = pre.count(r'\begin{tikzpicture}') - pre.count(r'\end{tikzpicture}')
        if tikz_depth > 0:
            continue  # Inside a tikzpicture, skip

        end_match = re.search(r'\\end\{axis\}', body[m.end():])
        if end_match:
            end = m.end() + end_match.end()
            axis_code = body[start:end]
            figures.append({
                'code': axis_code,
                'caption': '',
                'pre_defs': [],
                'is_axis': True,
            })

    return figures


def build_standalone(tikz_code: str, preamble: dict, source_path: str,
                     caption: str = "", pre_defs: list = None,
                     needs_xelatex: bool = False, is_axis: bool = False) -> str:
    """Build a complete standalone .tex file."""
    lines = []

    # Source comment
    rel_path = str(Path(source_path).relative_to(ROOT))
    lines.append(f"% Source: {rel_path}")
    if caption:
        lines.append(f"% Description: {caption}")
    if needs_xelatex:
        lines.append("% Requires: xelatex")
    lines.append("")

    lines.append(r"\documentclass[border=4pt]{standalone}")

    # Core packages - always include tikz
    core_packages = {"tikz"}
    if is_axis or r'\begin{axis}' in tikz_code or r'\addplot' in tikz_code:
        core_packages.add("pgfplots")

    # Collect all packages from preamble
    added_packages = set()
    if preamble.get('packages'):
        for pkg in preamble['packages']:
            # Extract package name
            pkg_name_match = re.search(r'\{([^}]+)\}$', pkg)
            if pkg_name_match:
                pkg_name = pkg_name_match.group(1)
                # Skip document-level packages not needed for standalone
                skip_pkgs = {'geometry', 'fancyhdr', 'setspace', 'hyperref',
                             'tcolorbox', 'enumitem', 'booktabs', 'array',
                             'colortbl', 'float', 'longtable', 'multicol',
                             'fontspec', 'titlesec', 'tocloft', 'appendix',
                             'natbib', 'biblatex', 'cite', 'cleveref',
                             'subcaption', 'caption', 'listings',
                             'framed', 'circuitikz', 'physics',
                             'parskip', 'inputenc', 'babel', 'csquotes',
                             'microtype', 'url', 'doi', 'siunitx',
                             'algorithm', 'algorithmic', 'algorithm2e',
                             'tabularx', 'multirow', 'makecell',
                             'adjustbox', 'pdfpages', 'lastpage',
                             'lipsum', 'blindtext', 'etoolbox',
                             'soul', 'ulem', 'cancel', 'minted',
                             'fancyvrb', 'verbatim', 'moreverb',
                             'fontawesome5', 'fontawesome', 'academicons',
                             'ragged2e', 'changepage', 'pdflscape',
                             'threeparttable', 'dirtree', 'forest',
                             'wrapfig', 'subfig', 'placeins',
                             'chemfig', 'tikz-3dplot', 'mhchem',
                             'thmtools', 'mdframed', 'needspace'}
                if pkg_name not in skip_pkgs:
                    core_packages.add(pkg_name)
                    added_packages.add(pkg)

    # Write packages
    for pkg in sorted(core_packages):
        if pkg == "pgfplots":
            lines.append(r"\usepackage{pgfplots}")
        elif pkg == "tikz":
            lines.append(r"\usepackage{tikz}")
        else:
            # Find original package line with options
            original = None
            for ap in added_packages:
                if ap.endswith("{" + pkg + "}"):
                    original = ap
                    break
            if original:
                lines.append(original)
            else:
                lines.append(f"\\usepackage{{{pkg}}}")

    # pgfplotsset compat
    if "pgfplots" in core_packages:
        lines.append(r"\pgfplotsset{compat=1.18}")

    # TikZ libraries
    if preamble.get('tikzlibs'):
        for lib in preamble['tikzlibs']:
            lines.append(lib)

    # PGFPlots libraries
    if preamble.get('pgflibs'):
        for lib in preamble['pgflibs']:
            lines.append(lib)

    lines.append("")

    # Color definitions
    if preamble.get('colors'):
        for color in preamble['colors']:
            lines.append(color)
        lines.append("")

    # PGFPlots sets (skip compat since we already set it)
    if preamble.get('pgfsets'):
        for ps in preamble['pgfsets']:
            if 'compat=' not in ps:
                lines.append(ps)
        lines.append("")

    # TikZ sets
    if preamble.get('tikzsets'):
        for ts in preamble['tikzsets']:
            lines.append(ts)
        lines.append("")

    # Custom commands
    if preamble.get('newcmds'):
        for cmd in preamble['newcmds']:
            lines.append(cmd.strip())
        lines.append("")

    # Def commands
    if preamble.get('defs'):
        for d in preamble['defs']:
            lines.append(d.strip())
        lines.append("")

    # Custom environments (only include if referenced in tikz code)
    # Skip by default - these usually aren't needed in standalone tikz

    # Macros
    if preamble.get('macros'):
        for macro in preamble['macros']:
            lines.append(macro)
        lines.append("")

    # Pre-definitions from just before the tikzpicture
    if pre_defs:
        for pd in pre_defs:
            lines.append(pd)
        lines.append("")

    lines.append(r"\begin{document}")

    # Wrap axis in tikzpicture if needed
    if is_axis:
        lines.append(r"\begin{tikzpicture}")
        lines.append(tikz_code)
        lines.append(r"\end{tikzpicture}")
    else:
        lines.append(tikz_code)

    lines.append(r"\end{document}")

    return "\n".join(lines) + "\n"


def sanitize_filename(name: str) -> str:
    """Convert filename to lowercase with underscores, no spaces."""
    name = name.lower()
    name = re.sub(r'[^\w\-.]', '_', name)
    name = re.sub(r'_+', '_', name)
    name = name.strip('_')
    return name


def find_csv_dependencies(content: str, source_dir: Path) -> list:
    """Find CSV files referenced by pgfplotstableread or similar."""
    deps = []
    patterns = [
        r'\\pgfplotstableread(?:\[.*?\])?\{(.*?\.csv)\}',
        r'\\addplot\s+table\s*(?:\[.*?\])?\s*\{(.*?\.csv)\}',
    ]
    for pat in patterns:
        for m in re.finditer(pat, content, re.DOTALL):
            csv_path = m.group(1)
            # Resolve relative path
            full_path = (source_dir / csv_path).resolve()
            if full_path.exists():
                deps.append((csv_path, full_path))
    return deps


def has_includegraphics(content: str) -> bool:
    """Check if tikzpicture contains includegraphics."""
    return bool(re.search(r'\\includegraphics', content))


def process_file(filepath: Path, seen_hashes: set) -> list:
    """Process a single .tex file and return list of (output_content, topic, filename) tuples."""
    results = []

    try:
        content = filepath.read_text(encoding='utf-8', errors='replace')
    except Exception:
        return results

    # Skip if no TikZ content
    if not re.search(r'tikzpicture|\\begin\{axis\}|pgfplots', content, re.IGNORECASE):
        return results

    # Skip very small files (likely fragments without useful content)
    if len(content.strip()) < 50:
        return results

    str_path = str(filepath)
    source_dir = filepath.parent

    # Determine category
    has_docclass = bool(re.search(r'\\documentclass', content))
    is_standalone = bool(re.search(r'\\documentclass(?:\[.*?\])?\{standalone\}', content))
    has_tikz = bool(re.search(r'\\begin\{tikzpicture\}', content))
    has_axis = bool(re.search(r'\\begin\{axis\}', content))

    if is_standalone:
        # Category A: Already standalone
        file_hash = get_file_hash(content)
        if file_hash in seen_hashes:
            return results
        seen_hashes.add(file_hash)

        # Handle \PARAM macro for tikzgif files
        if r'\PARAM' in content and r'\def\PARAM' not in content:
            content = content.replace(
                r'\begin{document}',
                '\\def\\PARAM{0.5}\n\\begin{document}'
            )

        # Add source comment if not present
        if not content.startswith('% Source:'):
            rel_path = str(filepath.relative_to(ROOT))
            content = f"% Source: {rel_path}\n" + content

        # Note external image dependencies
        if has_includegraphics(content):
            if '% Note:' not in content:
                content = content.replace(
                    r'\begin{document}',
                    '% Note: This file references external image(s) via \\includegraphics\n\\begin{document}'
                )

        topic = classify_topic(str_path, content)
        filename = sanitize_filename(filepath.stem + ".tex")
        results.append((content, topic, filename))

    elif not has_docclass and (has_tikz or has_axis):
        # Category B: Fragment - find parent preamble
        preamble = find_parent_preamble(filepath)

        file_hash = get_file_hash(content)
        if file_hash in seen_hashes:
            return results
        seen_hashes.add(file_hash)

        # The fragment IS the tikzpicture content
        if has_tikz:
            standalone = build_standalone(content, preamble, str_path)
        else:
            standalone = build_standalone(content, preamble, str_path, is_axis=True)

        topic = classify_topic(str_path, content)
        filename = sanitize_filename(filepath.stem + ".tex")
        results.append((standalone, topic, filename))

    elif has_docclass and not is_standalone and (has_tikz or has_axis):
        # Category C: Embedded in larger document
        preamble = extract_preamble(content)
        figures = find_tikzpictures(content)
        axis_figures = find_axis_envs(content)

        all_figs = figures + axis_figures
        if not all_figs:
            return results

        for i, fig in enumerate(all_figs, 1):
            fig_hash = get_file_hash(fig['code'])
            if fig_hash in seen_hashes:
                continue
            seen_hashes.add(fig_hash)

            is_axis = fig.get('is_axis', False)
            standalone = build_standalone(
                fig['code'], preamble, str_path,
                caption=fig.get('caption', ''),
                pre_defs=fig.get('pre_defs', []),
                needs_xelatex=preamble.get('needs_xelatex', False),
                is_axis=is_axis,
            )

            # Note external image dependencies
            if has_includegraphics(fig['code']):
                standalone = standalone.replace(
                    r'\begin{document}',
                    '% Note: This file references external image(s) via \\includegraphics\n\\begin{document}'
                )

            topic = classify_topic(str_path, fig['code'])
            basename = sanitize_filename(filepath.stem)
            filename = f"{basename}_fig{i:02d}.tex"
            results.append((standalone, topic, filename))

    return results


def find_parent_preamble(filepath: Path) -> dict:
    """For Category B fragments, find the parent document's preamble."""
    filename = filepath.name
    search_dirs = [filepath.parent, filepath.parent.parent]

    for search_dir in search_dirs:
        if not search_dir.exists():
            continue
        for f in search_dir.glob("*.tex"):
            if f == filepath:
                continue
            try:
                content = f.read_text(encoding='utf-8', errors='replace')
            except Exception:
                continue
            # Check if this file inputs our fragment
            if re.search(r'\\input\{.*?' + re.escape(filepath.stem) + r'\}', content):
                return extract_preamble(content)
            # Also check if it's a main document
            if re.search(r'\\documentclass', content) and re.search(r'\\begin\{document\}', content):
                return extract_preamble(content)

    # Return minimal preamble if no parent found
    return {
        'packages': [],
        'tikzlibs': [],
        'pgflibs': [],
        'pgfsets': [],
        'colors': [],
        'tikzsets': [],
        'newcmds': [],
        'macros': [],
        'needs_xelatex': False,
    }


def copy_csv_dependencies(content: str, source_dir: Path) -> str:
    """Copy CSV files to data/ and rewrite paths in content."""
    deps = find_csv_dependencies(content, source_dir)
    for orig_path, full_path in deps:
        # Copy to data dir
        dest = DATA_DIR / full_path.name
        if not dest.exists():
            try:
                shutil.copy2(full_path, dest)
            except Exception as e:
                print(f"  Warning: Could not copy CSV {full_path}: {e}")
        # Rewrite path in content
        content = content.replace(orig_path, f"../data/{full_path.name}")
    return content


def main():
    print("=" * 60)
    print("TikZ Figure Extraction")
    print("=" * 60)

    # Ensure output directories exist
    STAGING.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    seen_hashes = set()
    all_results = []
    topic_counts = defaultdict(int)
    files_scanned = 0
    skipped_dirs = 0

    # Walk the filesystem
    for dirpath, dirnames, filenames in os.walk(ROOT):
        # Skip excluded directories
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]

        for filename in filenames:
            if not filename.endswith('.tex'):
                continue

            filepath = Path(dirpath) / filename
            files_scanned += 1

            if files_scanned % 100 == 0:
                print(f"  Scanned {files_scanned} .tex files...")

            results = process_file(filepath, seen_hashes)
            for content, topic, fname in results:
                # Handle CSV dependencies
                content = copy_csv_dependencies(content, filepath.parent)

                # Resolve filename conflicts
                topic_dir = OUTPUT_DIR / topic
                dest = topic_dir / fname
                counter = 1
                while dest.exists():
                    base, ext = os.path.splitext(fname)
                    dest = topic_dir / f"{base}_{counter}{ext}"
                    counter += 1

                # Write file
                topic_dir.mkdir(parents=True, exist_ok=True)
                dest.write_text(content, encoding='utf-8')
                topic_counts[topic] += 1
                all_results.append((str(dest.relative_to(OUTPUT_DIR)), topic))

    print()
    print("=" * 60)
    print("EXTRACTION COMPLETE")
    print("=" * 60)
    print(f"Files scanned: {files_scanned}")
    print(f"Figures extracted: {len(all_results)}")
    print(f"Duplicates skipped: {len(seen_hashes) - len(all_results)}")
    print()
    print("Figures per topic:")
    for topic in sorted(topic_counts.keys()):
        print(f"  {topic}: {topic_counts[topic]}")

    # Write manifest
    manifest = {
        'total_scanned': files_scanned,
        'total_extracted': len(all_results),
        'by_topic': dict(topic_counts),
        'files': all_results,
    }
    manifest_path = OUTPUT_DIR / "scripts" / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))
    print(f"\nManifest written to {manifest_path}")

    # Clean up staging dir if empty
    if STAGING.exists() and not any(STAGING.iterdir()):
        STAGING.rmdir()


if __name__ == '__main__':
    main()
