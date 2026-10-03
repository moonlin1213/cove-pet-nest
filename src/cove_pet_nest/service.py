from .store import PetStore
from .images.service import ImageJobService
from .images.transport import configured_transport
from .growth import prepare_hatch


class NestService:
    def __init__(self,settings,store,jobs):
        self.settings,self.store,self.jobs=settings,store,jobs

    def state(self,*,offset=0,limit=100):
        state=self.store.state(offset=offset,limit=limit)
        state.update(user_name=self.settings.user_name,assistant_name=self.settings.assistant_name,
                     image_generation_configured=self.jobs.transport is not None)
        for pet in state['pets']:
            pet['jobs']=self.jobs.for_pet(pet['id'])
        return state

    def adopt(self,kind,name,request_id,*,actor):
        result=self.store.adopt(kind,name,request_id,actor=actor)
        if result['pet']['status']=='pending':
            pet=result['pet']
            self.jobs.enqueue(pet['id'],pet['id']+'-initial',{'stage':0,'kind':pet['kind']})
        return result

    def care(self,action,request_id,*,actor,pet_ids=None,scope='selected'):
        return self.store.care(action,request_id,actor=actor,pet_ids=pet_ids,scope=scope)

    async def tick(self):
        with self.store.connect() as db:
            eggs=[r['id'] for r in db.execute("SELECT id FROM pets WHERE kind='egg' AND stage=0 AND growth>=12 LIMIT 100")]
        for pet_id in eggs:
            brief=prepare_hatch(self.store,pet_id,now=self.store.now())
            if brief:
                self.jobs.enqueue(pet_id,pet_id+'-hatch',brief)
        return await self.jobs.run_once()


def build_service(settings):
    store=PetStore(settings.data_dir/'pets.sqlite3',timezone=settings.timezone)
    jobs=ImageJobService(store,settings.data_dir/'assets',configured_transport())
    return NestService(settings,store,jobs)
