"""容器入口使用的幂等初始化：表不存在时建表并写入种子数据，不删除既有数据。"""
from app.database import Base, SessionLocal, engine
from app import models  # noqa: F401
from app.seed import seed_all


def main() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_all(db)
    finally:
        db.close()
    print("幂等初始化完成")


if __name__ == "__main__":
    main()
