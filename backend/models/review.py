from datetime import datetime, timezone
from sqlalchemy import ForeignKey, String, Text, UniqueConstraint, JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
class Base(DeclarativeBase): pass
def now(): return datetime.now(timezone.utc)
class Document(Base):
 __tablename__='documents'; id:Mapped[str]=mapped_column(String,primary_key=True)
class DocumentVersion(Base):
 __tablename__='document_versions'; id:Mapped[str]=mapped_column(String,primary_key=True); document_id:Mapped[str]=mapped_column(ForeignKey('documents.id',ondelete='CASCADE'),index=True)
class AnalysisJob(Base):
 __tablename__='analysis_jobs'; id:Mapped[str]=mapped_column(String,primary_key=True); status:Mapped[str]=mapped_column(String,default='queued'); payload:Mapped[dict]=mapped_column(JSON,default=dict)
class JobDocument(Base):
 __tablename__='job_documents'; id:Mapped[str]=mapped_column(String,primary_key=True); job_id:Mapped[str]=mapped_column(ForeignKey('analysis_jobs.id',ondelete='CASCADE')); document_version_id:Mapped[str]=mapped_column(ForeignKey('document_versions.id',ondelete='CASCADE'))
class Finding(Base):
 __tablename__='findings'; id:Mapped[str]=mapped_column(String,primary_key=True); job_id:Mapped[str]=mapped_column(ForeignKey('analysis_jobs.id',ondelete='CASCADE')); stable_key:Mapped[str]=mapped_column(String); payload:Mapped[dict]=mapped_column(JSON,default=dict); __table_args__=(UniqueConstraint('job_id','stable_key'),)
class Conversation(Base):
 __tablename__='conversations'; id:Mapped[str]=mapped_column(String,primary_key=True); job_id:Mapped[str]=mapped_column(ForeignKey('analysis_jobs.id',ondelete='CASCADE')); document_version_id:Mapped[str]=mapped_column(ForeignKey('document_versions.id',ondelete='CASCADE')); __table_args__=(UniqueConstraint('job_id','document_version_id'),)
class ConversationMessage(Base):
 __tablename__='conversation_messages'; id:Mapped[str]=mapped_column(String,primary_key=True); conversation_id:Mapped[str]=mapped_column(ForeignKey('conversations.id',ondelete='CASCADE')); request_id:Mapped[str|None]=mapped_column(String); role:Mapped[str]=mapped_column(String); content:Mapped[str]=mapped_column(Text,default=''); status:Mapped[str]=mapped_column(String,default='streaming'); payload:Mapped[dict]=mapped_column(JSON,default=dict); created_at:Mapped[datetime]=mapped_column(default=now)
class RecommendedQuestion(Base):
 __tablename__='recommended_questions'; id:Mapped[str]=mapped_column(String,primary_key=True); conversation_id:Mapped[str]=mapped_column(ForeignKey('conversations.id',ondelete='CASCADE')); question:Mapped[str]=mapped_column(Text); payload:Mapped[dict]=mapped_column(JSON,default=dict); status:Mapped[str]=mapped_column(String,default='active')
