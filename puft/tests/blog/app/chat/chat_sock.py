from puft import Sock, log


class ChatSock(Sock):
    def on_connect(self):
        pass
    
    def on_send(self, data):
        data = {'number': 4321}
        self.socket.send(data, namespace=self.namespace)
        return data
