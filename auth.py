# Auth Module

class AuthManager:
    def __init__(self):
        self.users = {}
    
    def authenticate(self, username, password):
        """Authenticate a user"""
        if username in self.users:
            return self.users[username] == password
        return False
    
    def add_user(self, username, password):
        """Add a new user"""
        self.users[username] = password
    
    def remove_user(self, username):
        """Remove a user"""
        if username in self.users:
            del self.users[username]