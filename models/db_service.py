import uuid
import json
from typing import Optional, List
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import desc

from models.db_models import (
    Project, Character, WorldSetting, Chapter, Scene, 
    ChapterVersion, TimelineEvent, PlotArcRecord, Foreshadowing
)
from core.models import (
    CharacterSheet, WorldSetting as WorldSettingModel,
    ChapterOutline, SceneOutline, VolumeOutline, ChapterDraft
)


class ProjectService:
    def __init__(self, db: Session):
        self.db = db

    def create_project(
        self, 
        outline: str, 
        title: str = "",
        genre: str = "urban_fantasy",
        style: str = "web_novel",
        target_chapters: int = 100,
        words_per_chapter: int = 2000
    ) -> Project:
        project = Project(
            id=str(uuid.uuid4())[:8],
            title=title or "",
            outline=outline,
            genre=genre,
            style=style,
            target_chapters=target_chapters,
            words_per_chapter=words_per_chapter,
            approved=False
        )
        self.db.add(project)
        self.db.commit()
        self.db.refresh(project)
        return project

    def get_project(self, project_id: str) -> Optional[Project]:
        return self.db.query(Project).filter(Project.id == project_id).first()

    def get_all_projects(self) -> List[Project]:
        return self.db.query(Project).order_by(desc(Project.created_at)).all()

    def update_project(self, project_id: str, **kwargs) -> Optional[Project]:
        project = self.get_project(project_id)
        if project:
            for key, value in kwargs.items():
                if hasattr(project, key):
                    setattr(project, key, value)
            project.updated_at = datetime.utcnow()
            self.db.commit()
            self.db.refresh(project)
        return project

    def approve_project(self, project_id: str) -> Optional[Project]:
        return self.update_project(project_id, approved=True)

    def delete_project(self, project_id: str) -> bool:
        project = self.get_project(project_id)
        if project:
            from models.db_models import UserProject
            self.db.query(UserProject).filter(UserProject.project_id == project_id).delete(synchronize_session=False)
            self.db.delete(project)
            self.db.commit()
            return True
        return False

    def count_generated_chapters(self, project_id: str) -> int:
        return self.db.query(Chapter).filter(
            Chapter.project_id == project_id,
            Chapter.current_version > 0,
        ).count()


class CharacterService:
    def __init__(self, db: Session):
        self.db = db

    def create_character(self, project_id: str, char: CharacterSheet) -> Character:
        character = Character(
            project_id=project_id,
            name=char.name,
            goal=char.goal,
            personality=char.personality,
            relationships=char.relationships,
            status=char.status,
            memory=char.memory,
            appearance=char.appearance,
            abilities=char.abilities,
            voice=char.voice or {},
        )
        self.db.add(character)
        self.db.commit()
        self.db.refresh(character)
        return character

    def get_character(self, character_id: int) -> Optional[Character]:
        return self.db.query(Character).filter(Character.id == character_id).first()

    def get_character_by_name(self, project_id: str, name: str) -> Optional[Character]:
        return self.db.query(Character).filter(
            Character.project_id == project_id,
            Character.name == name
        ).first()

    def get_project_characters(self, project_id: str) -> List[Character]:
        return self.db.query(Character).filter(Character.project_id == project_id).all()

    def update_character(self, character_id: int, char: CharacterSheet) -> Optional[Character]:
        character = self.get_character(character_id)
        if character:
            character.name = char.name
            character.goal = char.goal
            character.personality = char.personality
            character.relationships = char.relationships
            character.status = char.status
            character.memory = char.memory
            character.appearance = char.appearance
            character.abilities = char.abilities
            character.voice = char.voice or {}
            character.updated_at = datetime.utcnow()
            self.db.commit()
            self.db.refresh(character)
        return character

    def update_character_by_name(self, project_id: str, name: str, char: CharacterSheet) -> Optional[Character]:
        character = self.get_character_by_name(project_id, name)
        if character:
            return self.update_character(character.id, char)
        return None

    def delete_character(self, character_id: int) -> bool:
        character = self.get_character(character_id)
        if character:
            self.db.delete(character)
            self.db.commit()
            return True
        return False

    def delete_project_characters(self, project_id: str):
        self.db.query(Character).filter(Character.project_id == project_id).delete()
        self.db.commit()

    def to_character_sheet(self, char: Character) -> CharacterSheet:
        return CharacterSheet(
            name=char.name,
            goal=char.goal,
            personality=char.personality or [],
            relationships=char.relationships or [],
            status=char.status or {},
            memory=char.memory or [],
            appearance=char.appearance,
            abilities=char.abilities or [],
            voice=char.voice or {},
        )


class WorldService:
    def __init__(self, db: Session):
        self.db = db

    def create_world(self, project_id: str, world: WorldSettingModel) -> WorldSetting:
        world_setting = WorldSetting(
            project_id=project_id,
            cultivation_system=world.cultivation_system,
            factions=world.factions,
            rules=world.rules,
            history=world.history,
            locations=world.locations
        )
        self.db.add(world_setting)
        self.db.commit()
        self.db.refresh(world_setting)
        return world_setting

    def get_world(self, project_id: str) -> Optional[WorldSetting]:
        return self.db.query(WorldSetting).filter(WorldSetting.project_id == project_id).first()

    def update_world(self, project_id: str, world: WorldSettingModel) -> Optional[WorldSetting]:
        world_setting = self.get_world(project_id)
        if world_setting:
            world_setting.cultivation_system = world.cultivation_system
            world_setting.factions = world.factions
            world_setting.rules = world.rules
            world_setting.history = world.history
            world_setting.locations = world.locations
            world_setting.updated_at = datetime.utcnow()
            self.db.commit()
            self.db.refresh(world_setting)
        return world_setting

    def to_world_setting_model(self, ws: WorldSetting) -> WorldSettingModel:
        return WorldSettingModel(
            cultivation_system=ws.cultivation_system,
            factions=ws.factions or [],
            rules=ws.rules or [],
            history=ws.history or [],
            locations=ws.locations or []
        )

    def replace_world(self, project_id: str, world: WorldSettingModel) -> WorldSetting:
        existing = self.get_world(project_id)
        if existing:
            self.db.delete(existing)
            self.db.commit()
        return self.create_world(project_id, world)


class ChapterService:
    def __init__(self, db: Session):
        self.db = db

    def create_chapter(
        self, 
        project_id: str, 
        chapter_index: int,
        title: str,
        goal: str = "",
        conflict: str = "",
        guidance: str = ""
    ) -> Chapter:
        chapter = Chapter(
            project_id=project_id,
            chapter_index=chapter_index,
            title=title,
            goal=goal,
            conflict=conflict,
            status="draft",
            current_version=0,
            guidance=guidance
        )
        self.db.add(chapter)
        self.db.commit()
        self.db.refresh(chapter)
        return chapter

    def get_chapter(self, chapter_id: int) -> Optional[Chapter]:
        return self.db.query(Chapter).filter(Chapter.id == chapter_id).first()

    def get_chapter_by_index(self, project_id: str, chapter_index: int) -> Optional[Chapter]:
        return self.db.query(Chapter).filter(
            Chapter.project_id == project_id,
            Chapter.chapter_index == chapter_index
        ).first()

    def get_project_chapters(self, project_id: str) -> List[Chapter]:
        return self.db.query(Chapter).filter(
            Chapter.project_id == project_id
        ).order_by(Chapter.chapter_index).all()

    def delete_project_chapters(self, project_id: str):
        chapter_ids = [
            row[0] for row in self.db.query(Chapter.id).filter(Chapter.project_id == project_id).all()
        ]
        if chapter_ids:
            self.db.query(ChapterVersion).filter(ChapterVersion.chapter_id.in_(chapter_ids)).delete(synchronize_session=False)
            self.db.query(Scene).filter(Scene.chapter_id.in_(chapter_ids)).delete(synchronize_session=False)
        self.db.query(Chapter).filter(Chapter.project_id == project_id).delete(synchronize_session=False)
        self.db.commit()

    def update_chapter(self, chapter_id: int, **kwargs) -> Optional[Chapter]:
        chapter = self.get_chapter(chapter_id)
        if chapter:
            for key, value in kwargs.items():
                if hasattr(chapter, key):
                    setattr(chapter, key, value)
            chapter.updated_at = datetime.utcnow()
            self.db.commit()
            self.db.refresh(chapter)
        return chapter

    def finalize_chapter(self, chapter_id: int) -> Optional[Chapter]:
        return self.update_chapter(chapter_id, status="finalized")

    def add_chapter_version(
        self,
        chapter_id: int,
        content: str,
        word_count: int = 0,
        consistency_score: float = 1.0
    ) -> ChapterVersion:
        chapter = self.get_chapter(chapter_id)
        if not chapter:
            raise ValueError(f"Chapter {chapter_id} not found")
        
        version_num = chapter.current_version + 1
        version = ChapterVersion(
            chapter_id=chapter_id,
            version=version_num,
            content=content,
            word_count=word_count or len(content),
            consistency_score=consistency_score
        )
        self.db.add(version)
        chapter.current_version = version_num
        chapter.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(version)
        return version

    def get_chapter_versions(self, chapter_id: int) -> List[ChapterVersion]:
        return self.db.query(ChapterVersion).filter(
            ChapterVersion.chapter_id == chapter_id
        ).order_by(ChapterVersion.version).all()

    def get_latest_version(self, chapter_id: int) -> Optional[ChapterVersion]:
        return self.db.query(ChapterVersion).filter(
            ChapterVersion.chapter_id == chapter_id
        ).order_by(desc(ChapterVersion.version)).first()

    def to_chapter_outline(self, chapter: Chapter) -> ChapterOutline:
        scenes = [
            SceneOutline(
                description=s.description,
                characters=s.characters or [],
                location=s.location,
                mood=s.mood,
                target_words=s.target_words
            )
            for s in sorted(chapter.scenes, key=lambda x: x.scene_index)
        ] if chapter.scenes else []
        
        return ChapterOutline(
            title=chapter.title,
            goal=chapter.goal,
            conflict=chapter.conflict,
            scenes=scenes
        )

    def to_chapter_draft(self, chapter: Chapter) -> Optional[ChapterDraft]:
        latest = self.get_latest_version(chapter.id)
        if not latest:
            return None
        return ChapterDraft(
            volume_index=0,
            chapter_index=chapter.chapter_index,
            title=chapter.title,
            content=latest.content,
            word_count=latest.word_count,
            consistency_score=latest.consistency_score,
            version=latest.version
        )


class SceneService:
    def __init__(self, db: Session):
        self.db = db

    def create_scene(
        self,
        chapter_id: int,
        scene_index: int,
        description: str = "",
        characters: List[str] = None,
        location: str = "",
        mood: str = "",
        target_words: int = 800
    ) -> Scene:
        scene = Scene(
            chapter_id=chapter_id,
            scene_index=scene_index,
            description=description,
            characters=characters or [],
            location=location,
            mood=mood,
            target_words=target_words
        )
        self.db.add(scene)
        self.db.commit()
        self.db.refresh(scene)
        return scene

    def get_chapter_scenes(self, chapter_id: int) -> List[Scene]:
        return self.db.query(Scene).filter(
            Scene.chapter_id == chapter_id
        ).order_by(Scene.scene_index).all()

    def delete_chapter_scenes(self, chapter_id: int):
        self.db.query(Scene).filter(Scene.chapter_id == chapter_id).delete()
        self.db.commit()


class TimelineService:
    def __init__(self, db: Session):
        self.db = db

    def add_event(
        self,
        project_id: str,
        chapter_index: int,
        event_type: str = "plot",
        description: str = ""
    ) -> TimelineEvent:
        event = TimelineEvent(
            project_id=project_id,
            chapter_index=chapter_index,
            event_type=event_type,
            description=description
        )
        self.db.add(event)
        self.db.commit()
        self.db.refresh(event)
        return event

    def get_project_timeline(self, project_id: str, limit: int = 50) -> List[TimelineEvent]:
        return self.db.query(TimelineEvent).filter(
            TimelineEvent.project_id == project_id
        ).order_by(TimelineEvent.chapter_index, TimelineEvent.created_at).limit(limit).all()


class PlotArcService:
    def __init__(self, db: Session):
        self.db = db

    def add_arc(
        self,
        project_id: str,
        arc_type: str = "side",
        description: str = "",
        progress: float = 0.0
    ) -> PlotArcRecord:
        arc = PlotArcRecord(
            project_id=project_id,
            arc_type=arc_type,
            description=description,
            progress=progress
        )
        self.db.add(arc)
        self.db.commit()
        self.db.refresh(arc)
        return arc

    def get_project_arcs(self, project_id: str) -> List[PlotArcRecord]:
        return self.db.query(PlotArcRecord).filter(
            PlotArcRecord.project_id == project_id
        ).all()

    def update_arc_progress(self, arc_id: int, progress: float) -> Optional[PlotArcRecord]:
        arc = self.db.query(PlotArcRecord).filter(PlotArcRecord.id == arc_id).first()
        if arc:
            arc.progress = progress
            arc.updated_at = datetime.utcnow()
            self.db.commit()
            self.db.refresh(arc)
        return arc


class ForeshadowingService:
    def __init__(self, db: Session):
        self.db = db

    def plant(
        self,
        project_id: str,
        description: str,
        chapter_index: int,
        foreshadow_type: str = "clue",
        trigger_keywords: list[str] | None = None,
        payoff_condition: str = "",
        source_excerpt: str = "",
        close_by_chapter: int | None = None,
    ) -> Foreshadowing:
        existing = self.db.query(Foreshadowing).filter(
            Foreshadowing.project_id == project_id,
            Foreshadowing.description == description,
            Foreshadowing.planted_chapter == chapter_index,
        ).first()
        if existing:
            return existing
        foreshadow = Foreshadowing(
            project_id=project_id,
            description=description,
            foreshadow_type=foreshadow_type,
            trigger_keywords=trigger_keywords or [],
            payoff_condition=payoff_condition,
            source_excerpt=source_excerpt,
            planted_chapter=chapter_index,
            close_by_chapter=close_by_chapter,
            status="active"
        )
        self.db.add(foreshadow)
        self.db.commit()
        self.db.refresh(foreshadow)
        return foreshadow

    def resolve(
        self,
        foreshadow_id: int,
        chapter_index: int,
        description: str = ""
    ) -> Optional[Foreshadowing]:
        foreshadow = self.db.query(Foreshadowing).filter(Foreshadowing.id == foreshadow_id).first()
        if foreshadow:
            foreshadow.status = "resolved"
            foreshadow.resolved_chapter = chapter_index
            foreshadow.resolved_description = description
            foreshadow.updated_at = datetime.utcnow()
            self.db.commit()
            self.db.refresh(foreshadow)
        return foreshadow

    def get_project_foreshadowing(self, project_id: str) -> List[Foreshadowing]:
        return self.db.query(Foreshadowing).filter(
            Foreshadowing.project_id == project_id
        ).all()

    def get_unresolved(self, project_id: str) -> List[Foreshadowing]:
        return self.db.query(Foreshadowing).filter(
            Foreshadowing.project_id == project_id,
            Foreshadowing.status.in_(["active", "closing"])
        ).all()
