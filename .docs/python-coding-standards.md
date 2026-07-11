# Python Development Guidelines

A comprehensive guide for Python development following Clean Architecture principles, type safety, and modern best practices.

---

## Table of Contents

1. [Project Structure](#project-structure)
2. [Package Management](#package-management)
3. [Clean Architecture Layers](#clean-architecture-layers)
4. [Type Annotations](#type-annotations)
5. [Configuration Management](#configuration-management)
6. [Code Organization](#code-organization)
7. [Documentation Standards](#documentation-standards)
8. [Interfaces and Abstract Base Classes](#interfaces-and-abstract-base-classes)
9. [Error Handling](#error-handling)
10. [Best Practices](#best-practices)

---

## Project Structure

Use **src layout** for better package isolation and testing:

```
project_root/
├── .github/
│   └── python-instructions.md
├── src/
│   └── your_package/
│       ├── __init__.py
│       ├── domain/
│       ├── application/
│       ├── infrastructure/
│       └── api/
├── tests/
├── docs/
├── pyproject.toml
├── main.py
└── README.md
```

**Benefits of src layout:**
- Prevents accidental imports from local development
- Forces proper package installation
- Better test isolation
- Industry standard for modern Python projects

---

## Package Management

### Use `uv` (NOT pip)

`uv` is a fast, modern Python package manager written in Rust.

#### Installation
```powershell
# Install uv
pip install uv

# Or via official installer
curl -LsSf https://astral.sh/uv/install.sh | sh
```

#### Common Commands
```powershell
# Install dependencies (replaces pip install)
uv sync

# Add a new package (replaces pip install <package>)
uv add <package>

# Add dev dependency
uv add --dev <package>

# Run Python commands
uv run python main.py

# Run any command with project Python
uv run <command>

# Activate virtual environment (if needed)
.venv\Scripts\activate
```

### pyproject.toml Structure

```toml
[project]
name = "your-project"
version = "0.1.0"
description = "Project description"
authors = [
    { name = "Your Name", email = "your.email@example.com" }
]
readme = "README.md"
requires-python = ">=3.10"
dependencies = [
    "fastapi[standard]>=0.122.0",
    "pydantic>=2.0.0",
    "pydantic-settings>=2.0.0",
    "sqlalchemy>=2.0.0",
    "alembic>=1.13.0",
    # ... other dependencies
]

[tool.uv]
# Platform-specific requirements if needed
required-environments = ["sys_platform == 'win32'"]

[tool.uv.sources]
# Git dependencies
package-name = { git = "https://github.com/user/repo.git", rev = "v1.0.0" }

[dependency-groups]
dev = [
    "pytest>=8.0.0",
    "black>=24.0.0",
    "isort>=5.13.0",
    "mypy>=1.8.0",
]

[tool.black]
line-length = 88
target-version = ['py310']

[tool.isort]
profile = "black"
line_length = 88
```

---

## Clean Architecture Layers

Organize code into distinct layers with clear boundaries:

```
src/your_package/
├── domain/              # Core business logic (no external dependencies)
│   ├── entities/        # Domain models (Pydantic)
│   ├── dtos/           # Data Transfer Objects
│   ├── value_objects/  # Immutable value types (Enums, etc.)
│   ├── interfaces/     # Abstract interfaces (ABC)
│   └── exceptions/     # Domain-specific exceptions
│
├── application/         # Business logic orchestration
│   ├── services/       # Service layer (use cases)
│   └── workflows/      # Complex multi-step operations
│
├── infrastructure/      # External concerns (frameworks, I/O)
│   ├── database/       # Database implementations
│   ├── repositories/   # Data access implementations
│   ├── storage/        # File storage
│   └── external/       # Third-party integrations
│
└── api/                # Presentation layer
    ├── controllers/    # API endpoints
    ├── schemas/        # API request/response models
    ├── dependencies/   # Dependency injection
    └── middleware/     # HTTP middleware
```

### Layer Responsibilities

**Domain Layer** (innermost, no external dependencies):
- Business entities and rules
- Value objects and enums
- Interface definitions (contracts)
- Domain exceptions
- Pure Python, no framework code

**Application Layer**:
- Business logic orchestration
- Service classes coordinating domain objects
- Transaction boundaries
- Depends only on Domain layer

**Infrastructure Layer**:
- Database implementations
- Repository implementations
- External API clients
- File I/O operations
- Implements Domain interfaces

**API Layer** (outermost):
- HTTP controllers/routes
- Request/response models
- Authentication/authorization
- API-specific validation
- Depends on all other layers

---

## Type Annotations

**Always use type hints** for all function parameters, return types, and variables.

### Basic Type Hints

```python
from typing import Optional, List, Dict, Tuple, Any, Union
from datetime import datetime
from uuid import UUID

def process_user(
    user_id: str,
    name: str,
    age: int,
    email: Optional[str] = None,
    tags: List[str] = [],
    metadata: Dict[str, Any] = {}
) -> Dict[str, Any]:
    """Process user data and return result."""
    return {
        "user_id": user_id,
        "processed": True
    }
```

### Class Attributes

```python
from typing import ClassVar

class Repository:
    """Repository class with typed attributes."""

    # Instance attributes (use in __init__)
    session: AsyncSession
    cache: Optional[Cache]

    # Class-level constants
    TABLE_NAME: ClassVar[str] = "users"
    MAX_RETRIES: ClassVar[int] = 3

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.cache = None
```

### Generic Types

```python
from typing import TypeVar, Generic, Protocol

T = TypeVar('T')

class Repository(Generic[T]):
    """Generic repository for any entity type."""

    async def get_by_id(self, id: str) -> Optional[T]:
        """Get entity by ID."""
        pass

    async def list_all(self) -> List[T]:
        """List all entities."""
        pass
```

### Pydantic Models (Domain Entities)

Use Pydantic for runtime validation and type safety:

```python
from pydantic import BaseModel, Field, field_validator
from typing import Optional
from datetime import datetime
from uuid import UUID

class User(BaseModel):
    """
    Domain entity representing a user.

    Attributes:
        id: Unique user identifier.
        name: User's full name.
        email: User's email address.
        age: User's age (must be 18+).
        created_at: Timestamp of creation.
    """
    id: UUID
    name: str = Field(..., min_length=1, max_length=255)
    email: str = Field(..., pattern=r'^[\w\.-]+@[\w\.-]+\.\w+$')
    age: int = Field(..., ge=18, le=150)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: Optional[Dict[str, Any]] = Field(default=None)

    @field_validator('name')
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Ensure name is properly capitalized."""
        if not v.strip():
            raise ValueError("Name cannot be empty")
        return v.strip().title()

    model_config = {
        "from_attributes": True,  # Allow ORM model conversion
        "json_schema_extra": {
            "example": {
                "id": "123e4567-e89b-12d3-a456-426614174000",
                "name": "John Doe",
                "email": "john@example.com",
                "age": 30,
                "is_active": True
            }
        }
    }
```

---

## Configuration Management

Use **Pydantic Settings** for type-safe configuration from environment variables.

### Configuration Class

```python
"""
Application configuration module.

Loads configuration from environment variables with type validation.
"""

from typing import Optional
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseConfig(BaseSettings):
    """
    Database configuration settings.

    Environment variables should be prefixed with DB_.
    Example: DB_HOST, DB_PORT, DB_NAME

    Attributes:
        host: Database server hostname.
        port: Database server port.
        name: Database name.
        user: Database username.
        password: Database password (kept secret).
        pool_size: Connection pool size.
    """
    host: str = Field(..., description="Database host address")
    port: int = Field(5432, ge=1, le=65535, description="Database port")
    name: str = Field(..., description="Database name")
    user: str = Field(..., description="Database username")
    password: SecretStr = Field(..., description="Database password")
    pool_size: int = Field(10, ge=1, le=100, description="Connection pool size")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="DB_",  # Environment variables: DB_HOST, DB_PORT, etc.
        case_sensitive=False,
        extra="ignore"
    )

    @property
    def connection_url(self) -> str:
        """Generate database connection URL."""
        return (
            f"postgresql+asyncpg://{self.user}:{self.password.get_secret_value()}"
            f"@{self.host}:{self.port}/{self.name}"
        )


class APIConfig(BaseSettings):
    """API server configuration."""

    host: str = Field("0.0.0.0", description="Server bind address")
    port: int = Field(8000, ge=1, le=65535, description="Server port")
    debug: bool = Field(False, description="Debug mode")
    cors_origins: List[str] = Field(
        default_factory=lambda: ["http://localhost:3000"],
        description="Allowed CORS origins"
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="API_",
        case_sensitive=False
    )


class Settings(BaseSettings):
    """
    Root application settings.

    Aggregates all configuration sections.
    """
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    api: APIConfig = Field(default_factory=APIConfig)

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False
    )


# Global settings instance
settings = Settings()
```

### .env File

```bash
# Database Configuration
DB_HOST=localhost
DB_PORT=5432
DB_NAME=mydb
DB_USER=postgres
DB_PASSWORD=secret123
DB_POOL_SIZE=10

# API Configuration
API_HOST=0.0.0.0
API_PORT=8000
API_DEBUG=false
API_CORS_ORIGINS=["http://localhost:3000", "http://localhost:5173"]
```

---

## Code Organization

### File Structure

Every Python file should follow this structure:

```python
"""
Module Title

Brief description of what this module does.
Can be multiple lines explaining the purpose.
"""

# Standard library imports (alphabetical)
from abc import ABC, abstractmethod
from typing import Optional, List, Dict
from datetime import datetime
import json

# Third-party imports (alphabetical)
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

# Local imports (alphabetical by path)
from your_package.domain.entities.user import User
from your_package.domain.interfaces.repository import BaseRepository
from your_package.infrastructure.database.connection import get_db


# Constants (UPPER_CASE)
MAX_PAGE_SIZE: int = 100
DEFAULT_TIMEOUT: int = 30


# Module code below
class MyClass:
    """Class implementation."""
    pass
```

### Import Organization

Use **isort** for automatic import sorting:

```powershell
# Format imports
uv run isort .

# Check without modifying
uv run isort --check-only .
```

**Import order:**
1. Standard library
2. Third-party packages
3. Local application imports

**Within each group:** Alphabetical order

---

## Documentation Standards

### Module Docstring

```python
"""
Module Title

Detailed description of the module's purpose and functionality.
Can include usage examples, design decisions, or architectural notes.
"""
```

### Class Docstring (Google Style)

```python
class UserService:
    """
    Service for managing user-related business logic.

    Handles user creation, updates, authentication, and profile management.
    Coordinates between repositories, validators, and external services.

    Attributes:
        user_repository: Repository for user data access.
        email_service: Service for sending emails.
        cache: Optional cache for user lookups.

    Example:
        ```python
        service = UserService(user_repo, email_service)
        user = await service.create_user(user_data)
        ```
    """

    def __init__(
        self,
        user_repository: BaseUserRepository,
        email_service: EmailService,
        cache: Optional[Cache] = None
    ) -> None:
        """
        Initialize UserService with required dependencies.

        Args:
            user_repository: Repository for user database operations.
            email_service: Service for email notifications.
            cache: Optional caching layer for performance optimization.
        """
        self.user_repository = user_repository
        self.email_service = email_service
        self.cache = cache
```

### Function Docstring (Google Style)

```python
async def create_user(
    self,
    data: UserCreateDTO,
    send_welcome_email: bool = True
) -> User:
    """
    Create a new user account with validation and notifications.

    Validates user data, checks for duplicates, persists to database,
    and optionally sends a welcome email.

    Args:
        data: Data transfer object containing user creation data.
            Must include name, email, and password.
        send_welcome_email: Whether to send welcome email to user.
            Defaults to True.

    Returns:
        User: The newly created user entity with generated ID.

    Raises:
        UserAlreadyExists: If a user with the same email exists.
        ValidationError: If user data fails validation.
        DatabaseError: If database operation fails.

    Example:
        ```python
        user_data = UserCreateDTO(
            name="John Doe",
            email="john@example.com",
            password="secure123"
        )
        user = await service.create_user(user_data)
        print(f"Created user: {user.id}")
        ```
    """
    # Implementation here
    pass
```

### Short Function Docstring

For simple functions, a brief one-liner is acceptable:

```python
def calculate_total(items: List[float]) -> float:
    """Calculate the sum of all items."""
    return sum(items)

async def get_user_count(self) -> int:
    """Return the total number of users in the system."""
    return await self.user_repository.count()
```

---

## Interfaces and Abstract Base Classes

Use **ABC (Abstract Base Class)** to define interfaces.

### Repository Interface Pattern

```python
"""
User repository interface.

Defines the contract for user data access operations.
"""

from abc import ABC, abstractmethod
from typing import Optional, List, Tuple
from uuid import UUID

from your_package.domain.entities.user import User
from your_package.domain.dtos.user_dto import UserCreateDTO, UserUpdateDTO


class BaseUserRepository(ABC):
    """
    Abstract base class for user data access operations.

    Defines method signatures that all concrete user repository
    implementations must provide. Supports async operations for
    modern database drivers.

    Methods:
        create: Persist a new user entity.
        get_by_id: Retrieve user by unique identifier.
        get_by_email: Retrieve user by email address.
        list_all: Get paginated list of users.
        update: Update user fields.
        delete: Remove user from storage.
        exists: Check if user exists by ID.
    """

    @abstractmethod
    async def create(self, data: UserCreateDTO) -> User:
        """
        Create and persist a new user.

        Args:
            data: User creation data transfer object.

        Returns:
            User: The newly created user entity.

        Raises:
            DatabaseError: If creation fails.
        """
        pass

    @abstractmethod
    async def get_by_id(self, user_id: UUID) -> Optional[User]:
        """
        Retrieve a user by their unique identifier.

        Args:
            user_id: Unique user identifier.

        Returns:
            Optional[User]: User entity if found, None otherwise.
        """
        pass

    @abstractmethod
    async def get_by_email(self, email: str) -> Optional[User]:
        """
        Find a user by their email address.

        Args:
            email: User's email address.

        Returns:
            Optional[User]: User entity if found, None otherwise.
        """
        pass

    @abstractmethod
    async def list_all(
        self,
        page: int = 1,
        page_size: int = 20
    ) -> Tuple[List[User], int]:
        """
        Retrieve paginated list of users.

        Args:
            page: Page number (1-indexed).
            page_size: Number of items per page.

        Returns:
            Tuple[List[User], int]: List of users and total count.
        """
        pass

    @abstractmethod
    async def update(
        self,
        user_id: UUID,
        data: UserUpdateDTO
    ) -> User:
        """
        Update user fields.

        Args:
            user_id: ID of user to update.
            data: Update data transfer object.

        Returns:
            User: Updated user entity.

        Raises:
            UserNotFound: If user doesn't exist.
        """
        pass

    @abstractmethod
    async def delete(self, user_id: UUID) -> None:
        """
        Delete a user by ID.

        Args:
            user_id: ID of user to delete.

        Raises:
            UserNotFound: If user doesn't exist.
        """
        pass

    @abstractmethod
    async def exists(self, user_id: UUID) -> bool:
        """
        Check if a user exists.

        Args:
            user_id: User identifier to check.

        Returns:
            bool: True if user exists, False otherwise.
        """
        pass
```

### Repository Implementation

```python
"""
SQLAlchemy user repository implementation.

Concrete implementation of BaseUserRepository using SQLAlchemy ORM.
"""

from typing import Optional, List, Tuple
from uuid import UUID

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from your_package.domain.entities.user import User
from your_package.domain.dtos.user_dto import UserCreateDTO, UserUpdateDTO
from your_package.domain.interfaces.repositories.base_user_repository import (
    BaseUserRepository
)
from your_package.domain.exceptions.user_exceptions import UserNotFound
from your_package.infrastructure.database.models.user_model import UserModel


class UserRepository(BaseUserRepository):
    """
    SQLAlchemy-based user repository implementation.

    Provides asynchronous CRUD operations for users using SQLAlchemy ORM.

    Attributes:
        session: Async SQLAlchemy database session.
    """

    def __init__(self, session: AsyncSession) -> None:
        """
        Initialize repository with database session.

        Args:
            session: Async SQLAlchemy session for database operations.
        """
        self.session = session

    async def create(self, data: UserCreateDTO) -> User:
        """Create a new user in the database."""
        # Convert DTO to SQLAlchemy model
        user_model = UserModel(**data.model_dump())

        # Persist to database
        self.session.add(user_model)
        await self.session.commit()
        await self.session.refresh(user_model)

        # Convert ORM model to domain entity
        return User.model_validate(user_model)

    async def get_by_id(self, user_id: UUID) -> Optional[User]:
        """Retrieve user by ID."""
        result = await self.session.execute(
            select(UserModel).where(UserModel.id == user_id)
        )
        user_model = result.scalar_one_or_none()

        if user_model is None:
            return None

        return User.model_validate(user_model)

    async def get_by_email(self, email: str) -> Optional[User]:
        """Find user by email address."""
        result = await self.session.execute(
            select(UserModel).where(UserModel.email == email)
        )
        user_model = result.scalar_one_or_none()

        if user_model is None:
            return None

        return User.model_validate(user_model)

    # ... other method implementations
```

### Service Interface (Protocol)

For services, you can use **Protocol** for structural typing:

```python
"""
Email service protocol.

Defines the interface for email sending services.
"""

from typing import Protocol, List


class EmailService(Protocol):
    """
    Protocol defining email service interface.

    Any class implementing these methods can be used as an email service.
    """

    async def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        attachments: List[str] = []
    ) -> bool:
        """
        Send an email.

        Args:
            to: Recipient email address.
            subject: Email subject line.
            body: Email body content.
            attachments: List of file paths to attach.

        Returns:
            bool: True if sent successfully, False otherwise.
        """
        ...
```

---

## Error Handling

### Custom Exception Hierarchy

```python
"""
Domain exceptions for user operations.

Defines custom exceptions for user-related errors.
"""

from typing import Optional
from uuid import UUID


class UserException(Exception):
    """Base exception for all user-related errors."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(self.message)


class UserNotFound(UserException):
    """
    Raised when a user cannot be found.

    Attributes:
        user_id: ID of the missing user.
        message: Error message.
    """

    def __init__(self, user_id: Optional[UUID] = None) -> None:
        self.user_id = user_id
        if user_id:
            message = f"User with ID '{user_id}' not found."
        else:
            message = "User not found."
        super().__init__(message)


class UserAlreadyExists(UserException):
    """
    Raised when attempting to create a duplicate user.

    Attributes:
        email: Email address that already exists.
        message: Error message.
    """

    def __init__(self, email: str) -> None:
        self.email = email
        message = f"User with email '{email}' already exists."
        super().__init__(message)


class InvalidUserData(UserException):
    """
    Raised when user data fails validation.

    Attributes:
        field: Name of the invalid field.
        reason: Explanation of why validation failed.
    """

    def __init__(self, field: str, reason: str) -> None:
        self.field = field
        self.reason = reason
        message = f"Invalid {field}: {reason}"
        super().__init__(message)
```

### Exception Usage

```python
async def get_user(self, user_id: UUID) -> User:
    """
    Retrieve a user by ID.

    Raises:
        UserNotFound: If user doesn't exist.
    """
    user = await self.repository.get_by_id(user_id)

    if user is None:
        raise UserNotFound(user_id)

    return user

async def create_user(self, data: UserCreateDTO) -> User:
    """
    Create a new user.

    Raises:
        UserAlreadyExists: If email is already registered.
    """
    existing = await self.repository.get_by_email(data.email)

    if existing is not None:
        raise UserAlreadyExists(data.email)

    return await self.repository.create(data)
```

---

## Best Practices

### 1. Async/Await Throughout

Use async/await for all I/O operations:

```python
# Good
async def fetch_users(self) -> List[User]:
    """Fetch all users asynchronously."""
    return await self.repository.list_all()

# Good
async def process_data(self, data: List[Any]) -> None:
    """Process data with async operations."""
    tasks = [self.process_item(item) for item in data]
    await asyncio.gather(*tasks)
```

### 2. Dependency Injection

Always use constructor injection:

```python
class UserService:
    """Service with injected dependencies."""

    def __init__(
        self,
        user_repository: BaseUserRepository,
        email_service: EmailService,
        logger: Logger
    ) -> None:
        """Inject all dependencies via constructor."""
        self.user_repository = user_repository
        self.email_service = email_service
        self.logger = logger
```

### 3. Data Transfer Objects (DTOs)

Use separate models for different concerns:

```python
# Domain Entity (internal representation)
class User(BaseModel):
    """Domain entity with all fields."""
    id: UUID
    email: str
    hashed_password: str
    created_at: datetime

# Create DTO (API input)
class UserCreateDTO(BaseModel):
    """Data for creating a user."""
    email: str
    password: str  # Plain text, will be hashed

# Response DTO (API output)
class UserResponseDTO(BaseModel):
    """Public user data for API responses."""
    id: UUID
    email: str
    created_at: datetime
    # Note: No password field
```

### 4. Immutable Value Objects

```python
from enum import Enum

class UserRole(str, Enum):
    """User role enumeration."""
    ADMIN = "admin"
    USER = "user"
    GUEST = "guest"

class EmailAddress(BaseModel):
    """Value object for email addresses."""
    value: str = Field(..., pattern=r'^[\w\.-]+@[\w\.-]+\.\w+$')

    model_config = {
        "frozen": True  # Make immutable
    }
```

### 5. Repository Pattern

Always separate data access from business logic:

```python
# ✅ Good: Business logic in service, data access in repository
class UserService:
    async def activate_user(self, user_id: UUID) -> User:
        """Activate a user account."""
        user = await self.repository.get_by_id(user_id)
        if user is None:
            raise UserNotFound(user_id)

        user.is_active = True
        return await self.repository.update(user_id, user)

# ❌ Bad: Business logic mixed with data access
class UserRepository:
    async def activate_user(self, user_id: UUID) -> User:
        """Don't put business logic in repository!"""
        user = await self.get_by_id(user_id)
        user.is_active = True
        return await self.update(user)
```

### 6. Single Responsibility Principle

Each class should have one clear purpose:

```python
# ✅ Good: Separate concerns
class UserValidator:
    """Validates user data."""
    def validate_email(self, email: str) -> bool: ...

class UserRepository:
    """Handles user data persistence."""
    async def create(self, user: User) -> User: ...

class UserService:
    """Orchestrates user operations."""
    def __init__(self, repository, validator):
        self.repository = repository
        self.validator = validator
```

### 7. Logging

Use structured logging:

```python
from loguru import logger

async def create_user(self, data: UserCreateDTO) -> User:
    """Create a new user with logging."""
    logger.info(f"Creating user with email: {data.email}")

    try:
        user = await self.repository.create(data)
        logger.info(f"User created successfully: {user.id}")
        return user
    except Exception as e:
        logger.error(f"Failed to create user: {e}")
        raise
```

### 8. Testing

Structure tests to match your architecture:

```
tests/
├── unit/
│   ├── domain/
│   ├── application/
│   └── infrastructure/
├── integration/
│   ├── database/
│   └── api/
└── e2e/
    └── user_flows/
```

### 9. Code Formatting

Use Black and isort:

```powershell
# Format code
uv run black .
uv run isort .

# Check formatting
uv run black --check .
uv run isort --check-only .
```

### 10. Type Checking

Use mypy for static type checking:

```powershell
# Add to dev dependencies
uv add --dev mypy

# Run type checker
uv run mypy src/
```

---

## Quick Reference

### Project Setup Checklist

- [ ] Use src layout structure
- [ ] Configure pyproject.toml with uv
- [ ] Set up Clean Architecture layers
- [ ] Add type hints to all functions
- [ ] Configure Pydantic Settings for config
- [ ] Create ABC interfaces for repositories
- [ ] Define custom exception hierarchy
- [ ] Add module and function docstrings
- [ ] Configure Black and isort
- [ ] Set up pytest for testing

### Code Review Checklist

- [ ] All functions have type hints
- [ ] All public APIs have docstrings
- [ ] No business logic in repositories
- [ ] DTOs used for data transfer
- [ ] Exceptions properly raised and documented
- [ ] Async/await used for I/O operations
- [ ] Dependencies injected via constructor
- [ ] Imports organized (stdlib, third-party, local)
- [ ] Code formatted with Black
- [ ] Tests written for new functionality

---

## Additional Resources

- **Pydantic Documentation**: https://docs.pydantic.dev/
- **FastAPI Best Practices**: https://fastapi.tiangolo.com/tutorial/
- **Clean Architecture**: https://blog.cleancoder.com/uncle-bob/2012/08/13/the-clean-architecture.html
- **Python Type Hints**: https://docs.python.org/3/library/typing.html
- **uv Documentation**: https://github.com/astral-sh/uv

---

*This guide provides a foundation for building maintainable, type-safe Python applications. Adapt these patterns to your specific project needs while maintaining consistency and clarity.*
