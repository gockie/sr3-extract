---
title: 'SR3-Extract: Formation-aware batch extraction and completeness auditing of CMG reservoir simulation time-series'
tags:
  - Python
  - reservoir simulation
  - CMG
  - SR3
  - HDF5
  - carbon capture and storage
  - time-series extraction
authors:
  - name: Chisom K. Okwaraojimadu
    orcid: 0000-0003-3339-4002
    corresponding: true
    affiliation: 1
  - name: Justin Ezekiel
    affiliation: 1
affiliations:
  - name: Department of Earth, Energy, and Environment, University of Calgary, Calgary, Alberta, Canada
    index: 1
date: 24 November 2026
bibliography: paper.bib
---

# Summary

Numerical reservoir simulators from the Computer Modelling Group (CMG) write
their results to a binary SR3 file, an HDF5-structured archive [@hdf5] that
stores well, group, sector, and grid time-series for every simulated timestep.
A screening study typically comprises many scenario runs, and the analyst
usually needs only a small, fixed set of time-series quantities from each one,
such as cumulative injected and produced volumes, phase rates, average
reservoir pressure, and component-specific adsorbed and produced moles. In
common practice these are exported one run at a time through the CMG Results
graphical interface, a process that is slow, repetitive, and error-prone, and
that offers no systematic check that every intended simulation was run and
reached the end of its scheduled project.

`SR3-Extract` is an open-source Python command-line tool that reads CMG SR3
files directly and automates this extraction and auditing workflow. Pointed at
a folder, it discovers every SR3 file, selects a parameter set from a formation
keyword in the filename, and writes one spreadsheet per run named to match its
source. It reads only the datasets it requires, built on `h5py` [@hdf5],
`NumPy` [@numpy], and `pandas` [@pandas], so memory use stays low enough for
ordinary 64-bit desktop and laptop hardware where a whole-file read would
exhaust available memory. A built-in audit stage reports simulations that were
never run, runs flagged by row count, and, using the intended project duration
read from each case's CMG input deck, runs that stopped before reaching the end
of the project.

# Statement of need

Reproducible post-processing of reservoir simulation ensembles is a recurring
bottleneck in subsurface screening studies across petroleum engineering,
geothermal energy, and geological carbon storage [@bachu2003; @bachu2007]. The
standard manual export route does not scale to tens or hundreds of scenarios,
consumes sustained analyst attention, and is vulnerable to silent errors such
as selecting the wrong variable or mislabelling an output. Just as important,
it provides no record that an ensemble is complete: a run that encounters
convergence difficulties can terminate years before the scheduled project end,
and this is easily missed when results are inspected by eye.

`SR3-Extract` addresses these needs for any CMG-based study that requires
consistent, auditable extraction of time-series across many scenario files. It
was developed for a national-scale geological CO2 storage screening study for
Canada (in preparation) in which simulations were run across four
unconventional target formations, and it encapsulates the exact parameter sets
used in that study as pre-defined, formation-specific extraction profiles.
Three features distinguish it from an ad hoc export script. First, it is
formation-aware: the parameter set is chosen automatically per file, and
component-specific quantities (for example methane and carbon-dioxide adsorbed
moles) are matched to components by name, because the component index order
differs between simulation decks. Second, it is memory-lean: it reads only the
required HDF5 datasets rather than the full file, so large SR3 files process
reliably on standard hardware. Third, it audits completeness against ground
truth: the intended project duration is read directly from each CMG input deck
as the span between its first and last `DATE` keywords, and a run whose final
simulation time does not reach a configurable fraction of this duration is
flagged. This final-day criterion is more reliable than a timestep count alone,
because a run that stalls on convergence can accumulate many small timesteps,
and therefore many output rows, while still terminating well before the project
end.

Extraction accuracy was validated against values exported manually through the
CMG Results interface for the same simulation: across all shared report times
the two agreed to approximately seven significant figures, with a maximum
relative difference below $10^{-7}$, consistent with the single-precision
rounding of the manual export.

# Acknowledgements

This work was supported by the University of Calgary and by Natural Resources
Canada (Geological Survey of Canada). The authors acknowledge the Computer
Modelling Group for the reservoir simulation software whose output this tool
reads.

# References
