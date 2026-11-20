import pathlib

import pytest

SAMPLES = pathlib.Path(__file__).parent / "samples"


@pytest.fixture
def d01b_example():
    return (SAMPLES / "edifact" / "mig_d01b_example1.edi").read_bytes()


@pytest.fixture
def d96a_example():
    return (SAMPLES / "edifact" / "mig_d96a_example2.edi").read_bytes()
