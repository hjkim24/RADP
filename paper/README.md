# RADP Paper Draft

Target venue: OSDI / NSDI / EuroSys class systems conference (ACM `sigconf` two-column).

## Layout

```
paper/
  main.tex            # entry point. \input's each section.
  references.bib      # bibtex entries (placeholders for now)
  sections/
    abstract.tex      # 250-word abstract; full prose
    introduction.tex  # outline + TODO
    background.tex    # outline + TODO
    design.tex        # outline + TODO (5 subsections)
    implementation.tex# outline + TODO (4 subsections)
    evaluation.tex    # outline + TODO (8 subsections) — the headline
    discussion.tex    # outline (4 subsections)
    related.tex       # outline (4 subsections)
    conclusion.tex    # outline + TODO
  figures/            # PDF/PNG drop here. Naming: figN-{short-name}.pdf
```

## Build

```
cd paper
latexmk -pdf main.tex          # or
pdflatex main && bibtex main && pdflatex main && pdflatex main
```

Will need `acmart` document class — install via TeX Live (`tlmgr install
acmart`) or your distro's `texlive-publishers` package.

## Status

- Abstract: full prose, ready for first round of edits
- All other sections: detailed outlines marked `\todo{}` so an author
  can grep `\\todo` to find where prose still needs to land
- References: placeholders, real entries to follow related-work prose

## Source-of-truth pointers

The paper draws its numbers and findings from two long-form documents
that live at the repo root:

- `../experiments/REPORT.md` — paper-ready evaluation results organized
  by experiment ID. The §10 (Phase F + F.2) section is the new headline.
- `../PHASES.md` — implementation history, one section per phase, with
  the exact commit hash that landed each change. Use this to back
  any specific implementation claim with a live measurement record.

When writing prose, cross-reference these explicitly (e.g. "see
REPORT §10.4 for the full matrix") so reviewers can audit the source.

## Workflow

- Section outlines (the `\todo` blocks) are the contract: turning a
  bullet into prose should not require new measurement.
- If a claim needs a number we don't have, add it as `\todo{measure: ...}`
  rather than guessing.
- Headline figures (matrix, recovery CDF, profiler per-layer ms)
  should be generated from the JSONs in `experiments/results/` — do
  not hand-fabricate; the matrix table is large enough to mismatch
  a hand-edit silently.
