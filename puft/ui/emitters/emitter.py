from ...helpers.singleton import Singleton
from ..controllers.omen_controller import OmenController


class Emitter(metaclass=Singleton):
    """Emitter is a special class performing various tasks related to turbo.js actions, such as updating.
    
    It acts with Views, which calls methods from Emitters.
    
    Attributes:
        app_controller: Omen application controller to work with, mainly using methods related to turbo.js."""
    def __init__(self, app_controller: OmenController) -> None:
        self.app_controller = app_controller