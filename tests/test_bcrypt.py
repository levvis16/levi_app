from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

password = "mypassword"
print("Password:", repr(password))
print("Byte length:", len(password.encode("utf-8")))

hashed = pwd_context.hash(password)
print("Hash:", hashed)
assert pwd_context.verify(password, hashed)
print("Verification succeeded")