import pytest

from sequence import STATE_IDLE, Sequence, SequenceError, SequenceStep


def test_step_rejects_invalid_values():
    with pytest.raises(SequenceError, match="exposure"):
        SequenceStep(exposure=0, count=5)
    with pytest.raises(SequenceError, match="count"):
        SequenceStep(exposure=30, count=0)
    with pytest.raises(SequenceError, match="autofocus_every"):
        SequenceStep(exposure=30, count=5, autofocus_every=0)
    with pytest.raises(SequenceError, match="done_count"):
        SequenceStep(exposure=30, count=5, done_count=-1)


def test_step_is_complete():
    step = SequenceStep(exposure=30, count=3, done_count=2)
    assert not step.is_complete
    step.done_count = 3
    assert step.is_complete


def test_step_needs_autofocus_every_n():
    step = SequenceStep(exposure=30, count=10, autofocus_every=4)
    due = []
    for i in range(10):
        step.done_count = i
        due.append(step.needs_autofocus())
    # subs 0, 4, 8 (0-based) should trigger autofocus
    assert due == [i % 4 == 0 for i in range(10)]


def test_step_needs_autofocus_none_when_unset():
    step = SequenceStep(exposure=30, count=10)
    assert not step.needs_autofocus()


def test_sequence_requires_at_least_one_step():
    with pytest.raises(SequenceError, match="at least one step"):
        Sequence.from_steps([])


def test_sequence_skip_completed_steps():
    seq = Sequence.from_steps(
        [
            {"exposure": 30, "count": 5, "done_count": 5},  # already done
            {"exposure": 60, "count": 3, "done_count": 1},  # in progress
            {"exposure": 10, "count": 2},
        ]
    )
    assert seq.skip_completed_steps() is True
    assert seq.current_step == 1
    assert seq.current().exposure == 60


def test_sequence_skip_completed_steps_all_done():
    seq = Sequence.from_steps([{"exposure": 30, "count": 1, "done_count": 1}])
    assert seq.skip_completed_steps() is False
    assert seq.current() is None


def test_sequence_record_sub_done_advances_progress():
    seq = Sequence.from_steps([{"exposure": 30, "count": 2}, {"exposure": 60, "count": 1}])
    assert seq.progress() == {
        "state": STATE_IDLE,
        "current_step": 0,
        "total_steps": 2,
        "done_subs": 0,
        "total_subs": 3,
    }
    seq.record_sub_done()
    assert seq.done_subs() == 1
    assert not seq.current().is_complete
    seq.record_sub_done()
    assert seq.current().is_complete
    # move on to step 2 once step 1 is exhausted
    assert seq.skip_completed_steps() is True
    assert seq.current_step == 1
    seq.record_sub_done()
    assert seq.skip_completed_steps() is False


def test_sequence_record_sub_done_without_current_step_raises():
    seq = Sequence.from_steps([{"exposure": 30, "count": 1, "done_count": 1}])
    seq.skip_completed_steps()
    with pytest.raises(SequenceError, match="no current step"):
        seq.record_sub_done()


def test_sequence_to_from_dict_roundtrip():
    seq = Sequence.from_steps(
        [
            {"exposure": 30, "count": 5, "filter": "Luminance", "autofocus_every": 10},
            {"exposure": 120, "count": 2, "ccd_temperature": -10},
        ]
    )
    seq.current_step = 1
    seq.state = "running"
    restored = Sequence.from_dict(seq.to_dict())
    assert restored == seq
