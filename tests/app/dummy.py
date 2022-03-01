from puft import Controller, Service, PuftService


class DummyController(Controller):
    pass


class DummyService(Service):
    def __init__(self, service_config: dict) -> None:
        super().__init__(service_config)

        self.app = PuftService.instance()
        print(self.app)
