import pytest

from app.llm.client import extract_json
from app.llm.schemas import BrainResult, RoutineExtraction
from app.services.routine import clean


def test_extract_json_from_fenced_output():
    raw = 'Sure!\n```json\n{"reply": "hi", "action": {"type": "none"}}\n```\nHope that helps'
    assert BrainResult.model_validate_json(extract_json(raw)).reply == "hi"


def test_extract_json_without_object_fails():
    with pytest.raises(ValueError):
        extract_json("no json here")


def test_brain_result_null_action_is_fine():
    r = BrainResult.model_validate_json('{"reply": "ok", "action": null}')
    assert r.action is None


def test_brain_result_lenient_item_id():
    r = BrainResult.model_validate_json('{"reply": "", "action": {"type": "routine_draft_reply", "item_id": "12", '
                                        '"decision": "save"}}')
    assert r.action.item_id == 12


def test_unknown_action_is_rejected():
    with pytest.raises(ValueError):
        BrainResult.model_validate_json('{"reply": "", "action": {"type": "delete_everything"}}')


def test_routine_clean_drops_bad_times_and_sorts():
    ext = RoutineExtraction.model_validate({"is_routine": True, "slots": [
        {"weekday": "Mon", "start_time": "9:00", "end_time": "8:00", "course_title": "Algo"},
        {"weekday": "Sun", "start_time": "10:00", "course_title": "DBMS"},
        {"weekday": "Tue", "start_time": "25:99", "course_title": "Broken"},
    ]})
    out = clean(ext)
    assert [s["course_title"] for s in out["slots"]] == ["DBMS", "Algo"]
    assert out["slots"][1]["start_time"] == "09:00" and out["slots"][1]["end_time"] is None
    assert any("Broken" in n for n in out["uncertain_notes"])
