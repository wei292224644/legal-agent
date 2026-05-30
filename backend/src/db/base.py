"""SQLAlchemy DeclarativeBase 入口；所有 ORM model 继承自 Base。"""
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
