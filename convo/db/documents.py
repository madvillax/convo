from pathlib import Path
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from convo.db.models import DocumentRow


def upsert_document(
    session: Session,
    document_id: UUID,
    path: Path,
    content_hash: str,
    signature: str,
) -> None:
    values = {
        "id": document_id,
        "source_path": str(path),
        "content_hash": content_hash,
        "index_signature": signature,
    }
    statement = insert(DocumentRow).values(**values)
    session.execute(
        statement.on_conflict_do_update(
            index_elements=[DocumentRow.id],
            set_={
                "source_path": str(path),
                "content_hash": content_hash,
                "index_signature": signature,
            },
        )
    )
    # The upsert locks the document row until commit, serializing replacement.
