from .db import native_db


class orm:
    # Helper references for shorter writing at ORMs.
    # Ignore lines added for a workaround to fix issue:
    # https://github.com/microsoft/pylance-release/issues/187
    Model: any = native_db.Model  # type: ignore
    column = native_db.Column  # type: ignore
    integer = native_db.Integer  # type: ignore
    string = native_db.String  # type: ignore
    text = native_db.Text  # type: ignore
    float = native_db.Float  # type: ignore
    boolean = native_db.Boolean  # type: ignore
    foreign_key = native_db.ForeignKey  # type: ignore
    table = native_db.Table  # type: ignore
    check_constraint = native_db.CheckConstraint  # type: ignore
    relationship = native_db.relationship  # type: ignore
    backref = native_db.backref  # type: ignore
    pickle = native_db.PickleType  # type: ignore
    binary = native_db.LargeBinary  # type: ignore
    datetime = native_db.DateTime  # type: ignore