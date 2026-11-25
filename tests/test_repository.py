from synaptiq.model.database import Database
from synaptiq.model.repository import Repository
from synaptiq.model.retention import apply_review
from synaptiq.services.chunking import Chunk


def test_repository_persists_documents_and_reviews(tmp_path) -> None:
    db = Database(tmp_path / "study.db")
    try:
        repo = Repository(db)
        course_id = repo.get_or_create_course(" Biology ")
        lecture_id = repo.find_or_create_lecture(course_id, "Cell structure")
        document_id = repo.add_document(
            "content-hash",
            "Cells",
            None,
            [Chunk(ordinal=0, page=1, heading="Cells", text="The cell is the basic unit.")],
            lecture_id=lecture_id,
        )

        assert repo.list_documents(lecture_id=lecture_id)[0].id == document_id
        assert repo.scope_text([document_id]) == "[Cells] The cell is the basic unit."

        repo.add_cards(document_id, [("What is a cell?", "The basic unit of life.")])
        card = repo.load_cards()[0]
        repo.save_review(apply_review(card.state, recalled=True), recalled=True)

        assert repo.load_cards()[0].state.last_reviewed is not None
    finally:
        db.close()
