from app.services import polls
from app.services.polls import cancel_passed, general_winner


def test_cancel_needs_majority_and_min_votes(monkeypatch):
    monkeypatch.setattr(polls, "MIN_VOTES", 3)
    assert cancel_passed(3, 0)
    assert cancel_passed(14, 3)
    assert not cancel_passed(2, 0)        # too few votes
    assert not cancel_passed(2, 2)        # tie
    assert not cancel_passed(3, 5)


def test_single_vote_is_enough_with_min_one(monkeypatch):
    monkeypatch.setattr(polls, "MIN_VOTES", 1)
    assert cancel_passed(1, 0)
    assert not cancel_passed(0, 0)
    assert not cancel_passed(1, 1)
    assert general_winner([0, 1]) == 1
    assert general_winner([0, 0]) is None


def test_general_winner(monkeypatch):
    monkeypatch.setattr(polls, "MIN_VOTES", 3)
    assert general_winner([5, 12]) == 1
    assert general_winner([4, 4, 1]) is None   # tie at the top
    assert general_winner([1, 1, 0]) is None   # too few votes
    assert general_winner([0, 3, 0]) == 1
