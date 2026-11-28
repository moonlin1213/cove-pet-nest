"""Render only public visual vocabulary at the image-provider boundary."""
from .store import NestError

CHOICES = {
    'shape': ('lighthouse','lantern','book','windmill','telescope','sailboat','teapot','acorn',
              'maple-leaf','pinecone','mushroom','seashell','star','moon','cloud','flower','butterfly',
              'bird','fish','whale','rabbit','cat','fox','bear','kite','ball','drum','bell','piano',
              'camera','train','bicycle','rocket','compass','hourglass','music-box','treehouse'),
    'material': ('felt','yarn','plush','cotton','velvet','corduroy','linen','wood','paper','clay'),
    'color': ('orange','cream','gold','amber','red','rose','indigo','blue','teal','aqua',
              'sage','green','lilac','silver','chocolate','lavender','peach'),
    'detail': ('stars','dots','stripes','stitches','scallops','ribbons','waves','leaves',
               'blossoms','buttons','spirals','patchwork','beads','tassels','plain')
}


def render_appearance(value):
    if not isinstance(value,dict) or value.keys()!=CHOICES.keys() or any(
            value[key] not in choices for key,choices in CHOICES.items()):
        raise NestError('invalid_toy_appearance')
    return (f"A {value['color']} {value['material']} {value['shape']} toy, "
            f"with a {value['detail']} motif.")
