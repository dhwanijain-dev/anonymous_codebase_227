from sqlalchemy.orm import Session


class Repository:
    def __init__(self, db: Session):
        self.db = db

    @property
    def dialect(self) -> str:
        return self.db.get_bind().dialect.name
