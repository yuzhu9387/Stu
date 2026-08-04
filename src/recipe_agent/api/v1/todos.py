"""Authenticated grocery and household todo CRUD API."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel

from recipe_agent.api.dependencies import ScopeDependency
from recipe_agent.domain.todos.contracts import TodoCreate, TodoUpdate, TodoView
from recipe_agent.domain.todos.repository import TodoNotFoundError, TodoRepository

router = APIRouter(prefix="/api/v1/todos", tags=["todos"])


class TodoListResponse(BaseModel):
    todos: tuple[TodoView, ...]


def get_todo_repository(request: Request) -> TodoRepository:
    return TodoRepository(request.app.state.session_factory)


TodoRepositoryDependency = Annotated[TodoRepository, Depends(get_todo_repository)]


@router.get("", response_model=TodoListResponse)
async def list_todos(
    scope: ScopeDependency, repository: TodoRepositoryDependency
) -> TodoListResponse:
    return TodoListResponse(todos=await repository.list_for_scope(scope))


@router.post("", response_model=TodoView, status_code=status.HTTP_201_CREATED)
async def create_todo(
    payload: TodoCreate, scope: ScopeDependency, repository: TodoRepositoryDependency
) -> TodoView:
    return await repository.create(scope, payload)


@router.patch("/{todo_id}", response_model=TodoView)
async def update_todo(
    todo_id: UUID, payload: TodoUpdate, scope: ScopeDependency, repository: TodoRepositoryDependency
) -> TodoView:
    try:
        return await repository.update(scope, todo_id, payload)
    except TodoNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from error


@router.delete("/{todo_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_todo(
    todo_id: UUID, scope: ScopeDependency, repository: TodoRepositoryDependency
) -> Response:
    try:
        await repository.delete(scope, todo_id)
    except TodoNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)
