from datetime import datetime, timedelta
from pathlib import Path
import os
import base64
import pyotp

from dotenv import load_dotenv
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
import jwt
from sqlalchemy.orm import session

from . import database, models, schemas

load_dotenv()

SECRET_KEY = os.environ.get('SECRET_KEY')
ALGORITHM = os.environ.get('ALGORITHM')
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.environ.get('ACCESS_TOKEN_EXPIRE_MINUTES', 30))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.environ.get('REFRESH_TOKEN_EXPIRE_DAYS', 7))

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")


# TOTP functions
def generate_totp_secret():
    """Generate a random base32 encoded secret for TOTP"""
    return pyotp.random_base32()


def get_totp_provisioning_uri(username: str, secret: str):
    """Generate the provisioning URI for QR code generation"""
    totp = pyotp.TOTP(secret)
    return totp.provisioning_uri(name=username, issuer_name="HealthScan")


def verify_totp(secret: str, code: str):
    """Verify the TOTP code against the secret"""
    totp = pyotp.TOTP(secret)
    return totp.verify(code)


def create_access_token(data: dict):
    to_encode = data.copy()
    
    # Convert UserRole enum to string if present
    if "role" in to_encode and hasattr(to_encode["role"], "value"):
        to_encode["role"] = to_encode["role"].value
    
    # Add token type for validation
    to_encode.update({"token_type": "access"})
    
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})

    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

    return encoded_jwt


def create_refresh_token(data: dict):
    to_encode = data.copy()
    
    # Convert UserRole enum to string if present
    if "role" in to_encode and hasattr(to_encode["role"], "value"):
        to_encode["role"] = to_encode["role"].value
    
    # Add token type for validation
    to_encode.update({"token_type": "refresh"})
    
    expire = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire})

    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

    return encoded_jwt


def verify_token(token: str, credentials_exception, expected_token_type=None):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        
        # Extract user ID and role
        id = payload.get("user_id")
        role = payload.get("role")

        if id is None:
            raise credentials_exception
        
        # Extract and validate token type if required
        token_type = payload.get("token_type")
        if expected_token_type and token_type != expected_token_type:
            raise credentials_exception
            
        token_data = schemas.TokenData(id=int(id), role=role, token_type=token_type)
    except jwt.ExpiredSignatureError:
        raise credentials_exception
    except jwt.InvalidTokenError:
        raise credentials_exception
    return token_data


def verify_access_token(token: str, credentials_exception):
    return verify_token(token, credentials_exception, expected_token_type="access")


def verify_refresh_token(token: str, credentials_exception):
    return verify_token(token, credentials_exception, expected_token_type="refresh")


def get_current_user(
    token: str = Depends(oauth2_scheme), db: session = Depends(database.get_db)
):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=f"Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    token_data = verify_access_token(token, credentials_exception)
    user = db.query(models.User).filter(models.User.id == token_data.id).first()
    if user is None:
        raise credentials_exception
    return user
