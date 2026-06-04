from datetime import datetime
from typing import Optional
from sqlalchemy import Column, Integer, String, Text, Float, Boolean, DateTime, ForeignKey, JSON
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class Project(Base):
    __tablename__ = "projects"

    id = Column(String(32), primary_key=True)
    title = Column(String(256), default="")
    outline = Column(Text, nullable=False)
    genre = Column(String(64), default="urban_fantasy")
    style = Column(String(64), default="web_novel")
    target_chapters = Column(Integer, default=100)
    words_per_chapter = Column(Integer, default=2000)
    approved = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    characters = relationship("Character", back_populates="project", cascade="all, delete-orphan")
    world_setting = relationship("WorldSetting", back_populates="project", uselist=False, cascade="all, delete-orphan")
    chapters = relationship("Chapter", back_populates="project", cascade="all, delete-orphan")
    timeline_events = relationship("TimelineEvent", back_populates="project", cascade="all, delete-orphan")
    plot_arcs = relationship("PlotArcRecord", back_populates="project", cascade="all, delete-orphan")
    foreshadowing = relationship("Foreshadowing", back_populates="project", cascade="all, delete-orphan")


class Character(Base):
    __tablename__ = "characters"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(String(32), ForeignKey("projects.id"), nullable=False)
    name = Column(String(128), nullable=False)
    goal = Column(Text, default="")
    personality = Column(JSON, default=list)
    relationships = Column(JSON, default=list)
    status = Column(JSON, default=dict)
    memory = Column(JSON, default=list)
    appearance = Column(Text, default="")
    abilities = Column(JSON, default=list)
    voice = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    project = relationship("Project", back_populates="characters")


class WorldSetting(Base):
    __tablename__ = "world_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(String(32), ForeignKey("projects.id"), nullable=False)
    cultivation_system = Column(Text, default="")
    factions = Column(JSON, default=list)
    rules = Column(JSON, default=list)
    history = Column(JSON, default=list)
    locations = Column(JSON, default=list)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    project = relationship("Project", back_populates="world_setting")


class Chapter(Base):
    __tablename__ = "chapters"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(String(32), ForeignKey("projects.id"), nullable=False)
    chapter_index = Column(Integer, nullable=False)
    title = Column(String(256), nullable=False)
    goal = Column(Text, default="")
    conflict = Column(Text, default="")
    status = Column(String(32), default="draft")
    current_version = Column(Integer, default=1)
    guidance = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    project = relationship("Project", back_populates="chapters")
    versions = relationship("ChapterVersion", back_populates="chapter", cascade="all, delete-orphan")
    scenes = relationship("Scene", back_populates="chapter", cascade="all, delete-orphan")


class Scene(Base):
    __tablename__ = "scenes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    chapter_id = Column(Integer, ForeignKey("chapters.id"), nullable=False)
    scene_index = Column(Integer, nullable=False)
    description = Column(Text, default="")
    characters = Column(JSON, default=list)
    location = Column(String(256), default="")
    mood = Column(String(64), default="")
    target_words = Column(Integer, default=800)
    created_at = Column(DateTime, default=datetime.utcnow)

    chapter = relationship("Chapter", back_populates="scenes")


class ChapterVersion(Base):
    __tablename__ = "chapter_versions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    chapter_id = Column(Integer, ForeignKey("chapters.id"), nullable=False)
    version = Column(Integer, nullable=False)
    content = Column(Text, default="")
    word_count = Column(Integer, default=0)
    consistency_score = Column(Float, default=1.0)
    created_at = Column(DateTime, default=datetime.utcnow)

    chapter = relationship("Chapter", back_populates="versions")


class TimelineEvent(Base):
    __tablename__ = "timeline_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(String(32), ForeignKey("projects.id"), nullable=False)
    chapter_index = Column(Integer, nullable=False)
    event_type = Column(String(64), default="plot")
    description = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    project = relationship("Project", back_populates="timeline_events")


class PlotArcRecord(Base):
    __tablename__ = "plot_arcs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(String(32), ForeignKey("projects.id"), nullable=False)
    arc_type = Column(String(32), default="main")
    description = Column(Text, default="")
    progress = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    project = relationship("Project", back_populates="plot_arcs")


class Foreshadowing(Base):
    __tablename__ = "foreshadowing"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(String(32), ForeignKey("projects.id"), nullable=False)
    description = Column(Text, nullable=False)
    foreshadow_type = Column(String(32), default="clue")
    trigger_keywords = Column(JSON, default=list)
    payoff_condition = Column(Text, default="")
    source_excerpt = Column(Text, default="")
    planted_chapter = Column(Integer, nullable=False)
    close_by_chapter = Column(Integer, nullable=True)
    status = Column(String(32), default="active")
    resolved_chapter = Column(Integer, nullable=True)
    resolved_description = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    project = relationship("Project", back_populates="foreshadowing")


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(64), unique=True, nullable=False)
    password_hash = Column(String(256), nullable=False)
    email = Column(String(128), unique=True, nullable=True)
    nickname = Column(String(64), default="")
    role = Column(String(32), default="user")
    is_active = Column(Boolean, default=True)
    balance = Column(Float, default=0.0)
    total_recharged = Column(Float, default=0.0)
    total_consumed = Column(Float, default=0.0)
    last_login_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    projects = relationship("UserProject", back_populates="user", cascade="all, delete-orphan")


class UserProject(Base):
    __tablename__ = "user_projects"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    project_id = Column(String(32), ForeignKey("projects.id"), nullable=False)
    role = Column(String(32), default="owner")
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="projects")


class RechargeRecord(Base):
    __tablename__ = "recharge_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    amount = Column(Float, nullable=False)
    payment_method = Column(String(32), default="manual")
    status = Column(String(32), default="completed")
    description = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)


class ConsumptionRecord(Base):
    __tablename__ = "consumption_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    project_id = Column(String(32), nullable=True)
    amount = Column(Float, nullable=False)
    consumption_type = Column(String(32), default="generate_chapter")
    description = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
