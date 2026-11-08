"""The Ask field under a hostile sentence: the cost of one parse stays bounded on a large file.

The vocabulary is synthetic (random words, 2 000 WBS nodes, 500 resources, 300 code values,
20 000 name words): the size of a large P6 project, no real schedule."""

import random
import string
import time

import pytest

from xerscope.analysis import query
from xerscope.analysis.query import MAX_CHARS, Vocabulary

NODES = 2000
BOUND = 1.0  # seconds for one parse; measured well under it, the margin absorbs a slow CI runner


@pytest.fixture(scope="module")
def large():
    rng = random.Random(1)

    def word(n):
        return "".join(rng.choice(string.ascii_lowercase) for _ in range(n))

    return Vocabulary(
        wbs={f"w{i}": f"Z{i:04d} · {word(7).title()} {word(6)} {word(8)}" for i in range(NODES)},
        resources={f"r{i}": (f"R{word(4).upper()}", f"{word(6)} {word(7)}") for i in range(500)},
        codes={f"c{i}": ("Zone", f"Z{word(3)}", f"{word(5)} {word(6)}") for i in range(300)},
        words=frozenset(word(rng.randint(3, 10)) for _ in range(20_000)),
        ids={(f"a{i}",): f"A{i}" for i in range(5000)},
    )


def _timed(function, *arguments):
    start = time.perf_counter()
    value = function(*arguments)
    return value, time.perf_counter() - start


def test_a_sentence_naming_many_nodes_parses_under_a_second(large):
    """50 WBS codes in MAX_CHARS characters: each node is read, in bounded time."""
    sentence = " ".join(f"z{i:04d}" for i in range(NODES))[:MAX_CHARS]
    got, seconds = _timed(query.parse, sentence, large)
    assert seconds < BOUND, f"{seconds:.2f} s"
    ((_, named),) = got.clauses
    assert {atom.value for atom in named.items} == {f"w{i}" for i in range(50)} and not got.ignored
