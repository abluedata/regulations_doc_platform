from uuid import uuid4
from sqlalchemy import select, update, delete
from backend.models.review import *
class ReviewRepository:
 def __init__(self,factory): self.factory=factory
 def create_schema(self): Base.metadata.create_all(self.factory.kw['bind'])
 def get_or_create_conversation(self,job_id,document_version_id):
  with self.factory() as s:
   o=s.scalar(select(Conversation).where(Conversation.job_id==job_id,Conversation.document_version_id==document_version_id))
   if not o: o=Conversation(id=str(uuid4()),job_id=job_id,document_version_id=document_version_id); s.add(o); s.commit()
   return o.id
 def add_message(self,conversation_id,role,content,request_id=None,status='streaming',payload=None):
  with self.factory() as s:
   if request_id:
    old=s.scalar(select(ConversationMessage).where(ConversationMessage.conversation_id==conversation_id,ConversationMessage.request_id==request_id,ConversationMessage.role==role))
    if old:return old.id
   o=ConversationMessage(id=str(uuid4()),conversation_id=conversation_id,role=role,content=content,request_id=request_id,status=status,payload=payload or {}); s.add(o); s.commit(); return o.id
 def list_messages(self,conversation_id):
  with self.factory() as s:return list(s.scalars(select(ConversationMessage).where(ConversationMessage.conversation_id==conversation_id).order_by(ConversationMessage.created_at,ConversationMessage.id)))
 def replace_recommended_questions(self,conversation_id,questions):
  with self.factory() as s:
   s.execute(update(RecommendedQuestion).where(RecommendedQuestion.conversation_id==conversation_id).values(status='superseded'))
   for q in questions:s.add(RecommendedQuestion(id=str(uuid4()),conversation_id=conversation_id,question=q.get('question',''),payload=q,status='active'))
   s.commit()
 def delete_document(self,document_id):
  with self.factory() as s:s.execute(delete(Document).where(Document.id==document_id)); s.commit()
