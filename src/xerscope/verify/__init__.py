"""Independent checks of what xerscope reads and computes, strongest source first.

- ``p6_corpus``: P6 Professional 23.12.1's own output on the held-out corpus (the oracle).
- ``mpxj_cpm``: MPXJ's PrimaveraScheduler as a second engine (a hint; where P6 settled
  a difference against it, ``P6_SETTLED`` says so).
- ``mpxj_reader``: MPXJ as an independent reader of the XER tables.

``xerscope.crosscheck`` re-exports all of it for the CLI and the tests.
"""
