"""Names vulture reports as unused in src/ that are used, each with the reason (CONTRIBUTING.md, Verification).

vulture reads this file beside src/ (``uvx vulture@2.14.0 src tests/vulture_whitelist.py``): a name
used here counts as used. It is never imported. The checks registered by ``@rule`` (analysis/rules.py,
p6/, dcma/, decm/, integrity.py) are left out by ``ignore_decorators`` in pyproject.toml, not here.
A new entry names its reason; an entry whose name is gone is removed.
"""

from xml.parsers.expat import XMLParserType

from xerscope.analysis.ask.filters import _Facets
from xerscope.analysis.baseline_resolution import Resolution
from xerscope.analysis.cpm import CptResult
from xerscope.app.downloads import anonymizers_built
from xerscope.app.glossary import unknown_acronyms
from xerscope.xer.model import Snapshot
from xerscope.xer.pmxml import XmlBaseline

_ = [
    # Filter methods the ask parser calls by name: getattr(self, f"_{kind}") in _Facets.
    _Facets._float,
    _Facets._milestone,
    _Facets._loe,
    _Facets._word,
    # expat calls the handlers assigned to its parser (xer/pmxml.py).
    XMLParserType.StartElementHandler,
    XMLParserType.EndElementHandler,
    XMLParserType.CharacterDataHandler,
    # Result fields read by the tests on purpose: the contract the tests pin, not read by the app.
    CptResult.shift_h,  # tests/test_cpm.py, tests/test_reference.py
    Resolution.is_exact,  # tests/test_baseline_resolution.py
    Snapshot.projects_in_file,  # tests/test_audit_edges_xer.py
    # A field shown by the Debug page through dataclasses.fields(XmlBaseline) (app/xml_baselines.py).
    XmlBaseline.original_project_id,
    # Test-support helpers kept in src/ beside the state they read.
    anonymizers_built,  # tests/test_app.py, tests/test_downloads.py: the anonymizers held in the session
    unknown_acronyms,  # tests/test_glossary.py: acronyms of a page text missing from the glossary
]
