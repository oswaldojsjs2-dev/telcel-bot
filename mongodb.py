# mongodb.py
import os
import re
from pymongo import MongoClient
from dotenv import load_dotenv
from datetime import datetime, timedelta
import random
import string

load_dotenv()

class MongoDB:
    def __init__(self):
        self.client = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017"))
        self.db = self.client[os.getenv("DB_NAME", "bot_creditos")]
        self.user = self.db.users
        self.keys = self.db.keys

    def query_user(self, user_id):
        return self.user.find_one({"id": user_id})

    def insert_user(self, data):
        return self.user.insert_one(data)

    def admin(self, user_id):
        user = self.query_user(user_id)
        return user and user.get('role') in ['admin', 'owner']

    def is_banned(self, user_id):
        user = self.query_user(user_id)
        return user and user.get('banned') == True

    def ban_user(self, user_id):
        return self.user.update_one(
            {"id": user_id},
            {"$set": {"banned": True}}
        )

    def unban_user(self, user_id):
        return self.user.update_one(
            {"id": user_id},
            {"$set": {"banned": False}}
        )

    def create_key(self, days):
        """Crea una key única para activar premium"""
        prefix = "ELBUENMX"
        # Generar código aleatorio de 12 dígitos
        code = ''.join(random.choices(string.digits, k=12))
        key = f"{prefix}-{code}"
        
        # Calcular fecha de expiración
        expires_at = datetime.now() + timedelta(days=days)
        
        key_data = {
            "key": key,
            "days": days,
            "used": False,
            "used_by": None,
            "used_at": None,
            "created_at": datetime.now(),
            "expires_at": expires_at
        }
        
        self.keys.insert_one(key_data)
        return key

    def claim_key(self, key, user_id, username, first_name):
        """Canjea una key y activa premium"""
        key_data = self.keys.find_one({"key": key, "used": False})
        
        if not key_data:
            return False, "Key inválida o ya fue usada"
        
        # Verificar si la key expiró
        if key_data.get("expires_at") and key_data["expires_at"] < datetime.now():
            return False, "La key ha expirado"
        
        days = key_data.get("days", 0)
        
        # Calcular nueva fecha de premium
        user_data = self.query_user(user_id)
        if user_data and user_data.get("premium_until"):
            current_expiry = user_data["premium_until"]
            if current_expiry > datetime.now():
                new_expiry = current_expiry + timedelta(days=days)
            else:
                new_expiry = datetime.now() + timedelta(days=days)
        else:
            new_expiry = datetime.now() + timedelta(days=days)
        
        # Actualizar usuario
        self.user.update_one(
            {"id": user_id},
            {
                "$set": {
                    "premium_until": new_expiry,
                    "role": "premium",
                    "username": username,
                    "first_name": first_name,
                    "last_update": datetime.now()
                }
            },
            upsert=True
        )
        
        # Marcar key como usada
        self.keys.update_one(
            {"key": key},
            {
                "$set": {
                    "used": True,
                    "used_by": user_id,
                    "used_at": datetime.now()
                }
            }
        )
        
        return True, days, new_expiry

    def get_user_info(self, user_id):
        """Obtiene información del usuario para /me"""
        user = self.query_user(user_id)
        if not user:
            return None
        
        return {
            "id": user.get("id"),
            "name": user.get("first_name", "Unknown"),
            "username": user.get("username", "None"),
            "role": user.get("role", "free"),
            "premium_until": user.get("premium_until"),
            "banned": user.get("banned", False)
        }

    def is_premium(self, user_id):
        """Verifica si el usuario es premium activo"""
        user = self.query_user(user_id)
        if not user:
            return False
        
        premium_until = user.get("premium_until")
        if not premium_until:
            return False
        
        return premium_until > datetime.now()

    def get_key_info(self, key):
        """Obtiene información de una key"""
        return self.keys.find_one({"key": key})

    def get_all_keys(self, limit=100):
        """Obtiene todas las keys (para panel)"""
        return list(self.keys.find().sort("created_at", -1).limit(limit))