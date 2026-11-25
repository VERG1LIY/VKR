"""Local demonstration of the existing VKR core. No VK tokens, domain or LLM.
Run from the project folder: python offline_check.py --project .
Creates a disposable SQLite DB; reads, but never modifies, import_docs.
"""
import argparse,asyncio,json,sys,tempfile,hashlib
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--project',default='.');p.add_argument('--json-output');args=p.parse_args()
root=Path(args.project).resolve();sys.path.insert(0,str(root))
from database.repository import DocumentDatabase
from services.document_service import DocumentService
from services.llm_service import LLMProcessor

async def main():
 with tempfile.TemporaryDirectory(prefix='vkr-offline-') as tmp:
  db=DocumentDatabase('sqlite+aiosqlite:///'+str(Path(tmp)/'check.db'))
  llm=LLMProcessor();llm.enabled=False
  try:
   await db.initialize();assert db._session_factory is not None,'SQLite did not initialize'
   svc=DocumentService(db=db,llm=llm);folder=root/'import_docs'
   total_files=len([f for f in folder.iterdir() if f.is_file()])
   count=await svc.import_documents_from_folder(str(folder));total=await db.get_total_count()
   assert count==total and total>0
   repeated=await svc.import_documents_from_folder(str(folder));assert repeated==0 and await db.get_total_count()==total
   results=await svc.search_documents('Паспорт');assert results,'Search found no passport card'
   doc=results[0];downloaded=await svc.download_document(doc.doc_id);assert downloaded
   content,name=downloaded;src=Path(doc.file_path).read_bytes();assert content==src
   active=await svc.filter_documents(status='Активен');assert len(active)==total
   empty=await svc.search_documents('ZZZ_NO_SUCH_DOCUMENT_839174');assert empty==[]
   report={'mode':'Local core, without VK or LLM','total_example_files':total_files,'imported':count,'ignored_files':[f.name for f in folder.iterdir() if f.is_file() and f.suffix.lower() not in ('.docx','.pdf','.dwg')],'repeat_import':repeated,'query':'Паспорт','found':[{'id':d.doc_id,'title':d.title,'status':d.status} for d in results],'active_count':len(active),'download_file':name,'download_size_bytes':len(content),'download_sha256':hashlib.sha256(content).hexdigest(),'download_equals_original':content==src,'empty_query_count':len(empty),'checks_passed':7,'checks':['SQLite initialization','First folder import','Repeat import does not duplicate','Search for existing title','Status filtering','File retrieval equals source bytes','Nonexistent title returns no records']}
   print(json.dumps(report,ensure_ascii=False,indent=2))
   if args.json_output:Path(args.json_output).write_text(json.dumps(report,ensure_ascii=False,indent=2))
  finally:
   await llm.close();await db.close()
asyncio.run(main())
