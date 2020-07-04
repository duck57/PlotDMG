# Plot DMG (Directed Multigraph)

See the module-level docstring of `storyboard.py` for formatting expectations
of the `.tsv` input files.  `examples/blank-stub.tsv` is another wonderful
example.

## Usage

* `./storyboard.py some_story.tsv` will give 4 output files: an SVG and a PDF
  each for both the storyline and a graph of friendships.
* `./storyboard.py --help` displays more detailed information on command-line
  options, including links to graphviz documentation.

Play around with the `-d` and `-t` options to find the settings that best suit
your story.

* `-d LR` generally produces better output than `-d TB`, but this varies
  depending on the line density and looping.
* `-t line` produces grid-like output compared to `-t box`.

