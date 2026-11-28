from .store import PetStore
from .images.service import ImageJobService
from .images.transport import configured_transport
from .growth import prepare_next_stage,growth_target
from .album import AlbumService
from .creation_worker import CreationWorker


class NestService:
    def __init__(self,settings,store,jobs):
        self.settings,self.store,self.jobs=settings,store,jobs
        self.album=AlbumService(store,jobs)
        self.creation=CreationWorker(store)
        self.jobs.creation=self.creation

    def state(self,*,offset=0,limit=100):
        state=self.store.state(offset=offset,limit=limit)
        state.update(user_name=self.settings.user_name,assistant_name=self.settings.assistant_name,
                     image_generation_configured=self.jobs.transport is not None)
        for pet in state['pets']:
            pet['jobs']=self.jobs.for_pet(pet['id'])
            with self.store.connect() as db:
                current=db.execute('SELECT * FROM pet_stages WHERE pet_id=? AND stage=?',(pet['id'],pet['stage'])).fetchone()
                original=db.execute('SELECT * FROM pets WHERE id=?',(pet['id'],)).fetchone()
                pet['growth_progress']=growth_target(original,current,self.store) if current and pet['status']=='ready' else None
        state['image_edit_configured']=self.jobs.transport is not None and getattr(self.jobs.transport,'can_reference',True)
        return state

    def adopt(self,kind,name,request_id,*,actor):
        result=self.store.adopt(kind,name,request_id,actor=actor)
        from .history import record_stage
        with self.store.write() as db:
            pet=db.execute('SELECT * FROM pets WHERE id=?',(result['pet']['id'],)).fetchone()
            if pet['status']=='ready':record_stage(db,pet,pet['created_at'])
        if result['pet']['status']=='pending':
            pet=result['pet']
            self.jobs.enqueue(pet['id'],pet['id']+'-initial',{'stage':0,'kind':pet['kind']})
        return result

    def care(self,action,request_id,*,actor,pet_ids=None,scope='selected'):
        return self.store.care(action,request_id,actor=actor,pet_ids=pet_ids,scope=scope)

    async def tick(self):
        with self.store.connect() as db:
            pets=[r['id'] for r in db.execute("SELECT id FROM pets WHERE status='ready' ORDER BY created_at,id")]
        for pet_id in pets:
            brief=prepare_next_stage(self.store,pet_id)
            if brief:
                self.jobs.enqueue(pet_id,pet_id+'-stage-'+str(brief['stage']),brief)
        await self.creation.tick()
        return await self.jobs.run_once()


def build_service(settings):
    store=PetStore(settings.data_dir/'pets.sqlite3',timezone=settings.timezone)
    jobs=ImageJobService(store,settings.data_dir/'assets',configured_transport())
    return NestService(settings,store,jobs)
