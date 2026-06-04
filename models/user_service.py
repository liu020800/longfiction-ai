import logging
from datetime import datetime
from typing import Optional, List
from sqlalchemy.orm import Session
from models.db_models import User, UserProject, RechargeRecord, ConsumptionRecord

logger = logging.getLogger(__name__)


class UserService:
    def __init__(self, db: Session):
        self.db = db

    def get_user(self, user_id: int) -> Optional[User]:
        return self.db.query(User).filter(User.id == user_id).first()

    def get_user_by_username(self, username: str) -> Optional[User]:
        return self.db.query(User).filter(User.username == username).first()

    def get_user_by_email(self, email: str) -> Optional[User]:
        if not email:
            return None
        return self.db.query(User).filter(User.email == email).first()

    def create_user(self, username: str, password_hash: str, email: str = None, nickname: str = "", role: str = "user") -> User:
        user = User(
            username=username,
            password_hash=password_hash,
            email=email,
            nickname=nickname or username,
            role=role,
        )
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def update_user(self, user_id: int, **kwargs) -> Optional[User]:
        user = self.get_user(user_id)
        if not user:
            return None
        for key, value in kwargs.items():
            if hasattr(user, key) and value is not None:
                setattr(user, key, value)
        user.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(user)
        return user

    def update_last_login(self, user_id: int):
        user = self.get_user(user_id)
        if user:
            user.last_login_at = datetime.utcnow()
            self.db.commit()

    def deactivate_user(self, user_id: int) -> bool:
        user = self.get_user(user_id)
        if user:
            user.is_active = False
            self.db.commit()
            return True
        return False

    def delete_user(self, user_id: int) -> bool:
        user = self.get_user(user_id)
        if not user:
            return False
        self.db.query(UserProject).filter(UserProject.user_id == user_id).delete()
        self.db.query(RechargeRecord).filter(RechargeRecord.user_id == user_id).delete()
        self.db.query(ConsumptionRecord).filter(ConsumptionRecord.user_id == user_id).delete()
        self.db.delete(user)
        self.db.commit()
        return True

    def activate_user(self, user_id: int) -> bool:
        user = self.get_user(user_id)
        if user:
            user.is_active = True
            self.db.commit()
            return True
        return False

    def recharge(self, user_id: int, amount: float, payment_method: str = "manual", description: str = "") -> Optional[User]:
        if amount <= 0:
            return None
        user = self.get_user(user_id)
        if not user:
            return None
        user.balance += amount
        user.total_recharged += amount
        record = RechargeRecord(
            user_id=user_id,
            amount=amount,
            payment_method=payment_method,
            description=description,
        )
        self.db.add(record)
        self.db.commit()
        self.db.refresh(user)
        return user

    def get_user_projects(self, user_id: int) -> List[UserProject]:
        return self.db.query(UserProject).filter(UserProject.user_id == user_id).all()

    def bind_project(self, user_id: int, project_id: str, role: str = "owner") -> UserProject:
        existing = self.db.query(UserProject).filter(
            UserProject.user_id == user_id,
            UserProject.project_id == project_id,
        ).first()
        if existing:
            return existing
        up = UserProject(user_id=user_id, project_id=project_id, role=role)
        self.db.add(up)
        self.db.commit()
        self.db.refresh(up)
        return up

    def get_project_owner(self, project_id: str) -> Optional[User]:
        up = self.db.query(UserProject).filter(
            UserProject.project_id == project_id,
            UserProject.role == "owner",
        ).first()
        if up:
            return self.get_user(up.user_id)
        return None

    def has_project_access(self, user_id: int, project_id: str) -> bool:
        up = self.db.query(UserProject).filter(
            UserProject.user_id == user_id,
            UserProject.project_id == project_id,
        ).first()
        return up is not None

    def get_recharge_history(self, user_id: int, limit: int = 50) -> List[RechargeRecord]:
        return self.db.query(RechargeRecord).filter(
            RechargeRecord.user_id == user_id,
        ).order_by(RechargeRecord.created_at.desc()).limit(limit).all()

    def get_consumption_history(self, user_id: int, limit: int = 50) -> List[ConsumptionRecord]:
        return self.db.query(ConsumptionRecord).filter(
            ConsumptionRecord.user_id == user_id,
        ).order_by(ConsumptionRecord.created_at.desc()).limit(limit).all()

    def list_users(self, offset: int = 0, limit: int = 50) -> List[User]:
        return self.db.query(User).offset(offset).limit(limit).all()

    def user_to_dict(self, user: User) -> dict:
        return {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "nickname": user.nickname,
            "role": user.role,
            "is_active": user.is_active,
            "balance": round(user.balance, 2),
            "total_recharged": round(user.total_recharged, 2),
            "total_consumed": round(user.total_consumed, 2),
            "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
            "created_at": user.created_at.isoformat() if user.created_at else None,
        }
