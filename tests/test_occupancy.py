import numpy as np

from mio_core_services.perception.backend import DetectedFace
from mio_core_services.perception.occupancy import Occupancy
from mio_core_services.perception.store import FaceStore


def _vec(*values: float) -> np.ndarray:
    return np.asarray(values, dtype=np.float32)


def _face(*values: float, facing: bool = True) -> DetectedFace:
    return DetectedFace(embedding=_vec(*values), facing=facing)


def test_facing_detection_creates_unnamed_person():
    store = FaceStore()
    occupancy = Occupancy(store)
    snapshot = occupancy.apply([_face(1, 0, 0, 0)])

    assert len(snapshot.occupants) == 1
    occupant = snapshot.occupants[0]
    assert occupant.name is None
    assert occupant.new_this_session is True
    assert store.count() == 1
    assert "unrecognized person" in snapshot.presence_text()


def test_profile_faces_are_ignored():
    occupancy = Occupancy(FaceStore())
    snapshot = occupancy.apply([_face(1, 0, 0, 0, facing=False)])

    assert snapshot.occupants == []
    assert snapshot.presence_text() is None


def test_leave_clears_occupancy_without_queueing():
    occupancy = Occupancy(FaceStore())
    occupancy.apply([_face(1, 0, 0, 0)])
    snapshot = occupancy.apply([])

    assert snapshot.occupants == []
    assert snapshot.presence_text() is None


def test_same_face_keeps_id_and_is_not_new_again():
    occupancy = Occupancy(FaceStore())
    first = occupancy.apply([_face(1, 0, 0, 0)])
    person_id = first.occupants[0].person_id
    second = occupancy.apply([_face(1, 0, 0, 0)])

    assert second.occupants[0].person_id == person_id
    assert second.occupants[0].new_this_session is False


def test_known_store_match_uses_saved_name():
    store = FaceStore()
    store.upsert("sarah", _vec(0, 1, 0, 0), name="Sarah")
    occupancy = Occupancy(store)
    snapshot = occupancy.apply([_face(0, 1, 0, 0)])

    assert snapshot.occupants[0].person_id == "sarah"
    assert snapshot.occupants[0].name == "Sarah"
    assert "Sarah" in snapshot.presence_text()


def test_return_this_session_is_not_new():
    occupancy = Occupancy(FaceStore())
    occupancy.apply([_face(1, 0, 0, 0)])
    occupancy.apply([])
    snapshot = occupancy.apply([_face(1, 0, 0, 0)])

    assert snapshot.occupants[0].new_this_session is False


def test_chroma_store_round_trips_named_embedding(tmp_path):
    path = str(tmp_path)
    FaceStore(path).upsert("sarah", _vec(0, 1, 0, 0), name="Sarah")
    reloaded = FaceStore(path)
    match = reloaded.match(_vec(0, 1, 0, 0))

    assert match is not None
    assert match.id == "sarah"
    assert match.name == "Sarah"
