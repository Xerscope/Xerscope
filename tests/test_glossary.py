"""Every acronym a page shows is spelled out: in the glossary, and in the help of its column or card."""

import pytest
from test_app import _ok, app  # noqa: F401 (app is a fixture)

from xerscope.analysis.standards import builtin_standards
from xerscope.app.glossary import GLOSSARY, acronyms, spelled_out, unknown_acronyms
from xerscope.app.ui import COLUMNS

PAGES = [
    "views/overview.py",
    "views/gantt.py",
    "views/activity.py",
    "views/health.py",
    "views/audit.py",
    "views/changelog.py",
    "views/earned_value.py",
    "views/milestones.py",
    "views/ppc.py",
    "views/export.py",
    "views/debug.py",
]


def test_spelled_out_names_each_acronym_once():
    text = spelled_out("SPI (labor units) = EV / PV, SPI again, wd")
    assert text.splitlines()[0] == "SPI: Schedule Performance Index. " + GLOSSARY["SPI"][1]
    assert acronyms("SPI (labor units) = EV / PV, SPI again, wd") == ["SPI", "EV", "PV", "wd"]
    assert spelled_out("Status") == ""


def test_every_column_label_is_in_the_glossary():
    unknown = {label: unknown_acronyms(label) for label, _kind in COLUMNS.values() if unknown_acronyms(label)}
    assert not unknown


@pytest.mark.parametrize("standard_id", ["P6", "DCMA", "DECM", "INTEGRITY"])
def test_every_check_name_is_in_the_glossary(standard_id):
    standard = builtin_standards()[standard_id]
    unknown = {metric.id: unknown_acronyms(metric.name) for metric in standard.metrics if unknown_acronyms(metric.name)}
    assert not unknown


def test_every_card_spells_out_its_acronyms(app):  # noqa: F811
    for page in PAGES:
        app.switch_page(page).run()
        _ok(app)
        for card in app.metric:
            assert not unknown_acronyms(card.label), (page, card.label)
            for token in acronyms(card.label):
                assert GLOSSARY[token][0] in (card.help or ""), (page, card.label, token)


def test_the_glossary_is_under_every_page(app):  # noqa: F811
    for page in PAGES:
        app.switch_page(page).run()
        assert any(box.label == "Glossary" for box in app.sidebar.expander), page
