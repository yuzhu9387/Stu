"use client";

import { Basket, Check, ListChecks, PencilSimple, Plus, Trash } from "@phosphor-icons/react";
import { useState, type FormEvent } from "react";

import { WorkspaceDialog } from "@/components/workspace-dialog";
import { useLocale } from "@/i18n/locale-context";
import { api } from "@/lib/api";
import { useResource } from "@/lib/use-resource";
import type { Todo } from "@/lib/workspace-types";

export function TodoBoard() {
  const { locale } = useLocale();
  const chinese = locale === "zh-CN";
  const resource = useResource<{ todos: Todo[] }>("/api/v1/todos");
  const [editing, setEditing] = useState<Todo | null | undefined>(undefined);
  const [category, setCategory] = useState<"grocery" | "todo">("grocery");

  async function toggle(item: Todo) {
    await api<Todo>(`/api/v1/todos/${item.id}`, {
      method: "PATCH",
      body: JSON.stringify({ completed: !item.completed }),
    });
    await resource.reload();
  }

  async function remove(item: Todo) {
    await api<void>(`/api/v1/todos/${item.id}`, { method: "DELETE" });
    await resource.reload();
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    await api<Todo>(editing ? `/api/v1/todos/${editing.id}` : "/api/v1/todos", {
      method: editing ? "PATCH" : "POST",
      body: JSON.stringify({
        category: String(form.get("category")),
        title: String(form.get("title")),
        note: String(form.get("note")) || null,
        due_on: String(form.get("due_on")) || null,
        visibility: String(form.get("visibility")),
      }),
    });
    setEditing(undefined);
    await resource.reload();
  }

  function add(type: "grocery" | "todo") {
    setCategory(type);
    setEditing(null);
  }

  const items = resource.data?.todos ?? [];

  return (
    <section className="workspace-page todo-board">
      <header className="workspace-page-header">
        <div><p className="warm-eyebrow">{chinese ? "家务清单" : "HOUSEHOLD LISTS"}</p><h1>{chinese ? "小事，也安排得从容" : "Little things, held lightly"}</h1><p>{chinese ? "采购和待办放在一个安静、清楚的地方。" : "Groceries and everyday tasks, side by side and easy to share."}</p></div>
      </header>
      <div className="todo-columns">
        {(["grocery", "todo"] as const).map((type) => {
          const columnItems = items.filter((item) => item.category === type);
          return <section className="todo-column" key={type}>
            <header><div className={`todo-icon ${type}`}>{type === "grocery" ? <Basket size={22} weight="duotone" /> : <ListChecks size={22} weight="duotone" />}</div><div><p>{type === "grocery" ? (chinese ? "采购" : "GROCERY") : chinese ? "待办" : "TODO"}</p><h2>{type === "grocery" ? (chinese ? "买些什么" : "For the kitchen") : chinese ? "要做的事" : "Around the home"}</h2></div><button aria-label={type === "grocery" ? (chinese ? "添加采购" : "Add grocery") : chinese ? "添加待办" : "Add todo"} className="icon-button" type="button" onClick={() => add(type)}><Plus size={19} weight="bold" /></button></header>
            <div className="todo-list">
              {columnItems.map((item) => <article className={item.completed ? "completed" : ""} key={item.id}>
                <button aria-label={chinese ? "切换完成状态" : "Toggle completion"} className="todo-check" type="button" onClick={() => void toggle(item)}>{item.completed ? <Check size={14} weight="bold" /> : null}</button>
                <div><h3>{item.title}</h3>{item.note ? <p>{item.note}</p> : null}<small>{item.due_on ? new Intl.DateTimeFormat(locale, { month: "short", day: "numeric" }).format(new Date(`${item.due_on}T12:00:00`)) : item.is_owned_by_current_account ? (chinese ? "我的项目" : "Mine") : item.owner_display_name}</small></div>
                {item.is_owned_by_current_account ? <div className="todo-actions"><button aria-label={chinese ? "编辑项目" : "Edit item"} type="button" onClick={() => { setCategory(item.category); setEditing(item); }}><PencilSimple size={15} /></button><button aria-label={chinese ? "删除项目" : "Delete item"} type="button" onClick={() => void remove(item)}><Trash size={15} /></button></div> : null}
              </article>)}
              {columnItems.length === 0 ? <button className="empty-todo" type="button" onClick={() => add(type)}><Plus size={17} /> {chinese ? "添加第一项" : "Add the first item"}</button> : null}
            </div>
            <footer><span>{columnItems.filter((item) => item.completed).length}/{columnItems.length} {chinese ? "已完成" : "complete"}</span><button type="button" onClick={() => add(type)}><Plus size={16} /> {chinese ? "新增" : "Add"}</button></footer>
          </section>;
        })}
      </div>
      <WorkspaceDialog open={editing !== undefined} title={editing ? (chinese ? "编辑项目" : "Edit item") : chinese ? "新增项目" : "Add item"} onClose={() => setEditing(undefined)}>
        <form className="workspace-form" onSubmit={save}>
          <label><span>{chinese ? "类型" : "List"}</span><select name="category" defaultValue={editing?.category ?? category}><option value="grocery">{chinese ? "采购" : "Grocery"}</option><option value="todo">{chinese ? "待办" : "Todo"}</option></select></label>
          <label><span>{chinese ? "可见范围" : "Visibility"}</span><select name="visibility" defaultValue={editing?.visibility ?? "family"}><option value="family">{chinese ? "家庭" : "Family"}</option><option value="private">{chinese ? "仅自己" : "Private"}</option></select></label>
          <label className="wide-field"><span>{chinese ? "内容" : "Title"}</span><input name="title" required defaultValue={editing?.title} /></label>
          <label className="wide-field"><span>{chinese ? "备注" : "Note"}</span><textarea name="note" rows={3} defaultValue={editing?.note ?? ""} /></label>
          <label className="wide-field"><span>{chinese ? "日期" : "Due date"}</span><input name="due_on" type="date" defaultValue={editing?.due_on ?? ""} /></label>
          <div className="form-actions wide-field"><button className="secondary-action" type="button" onClick={() => setEditing(undefined)}>{chinese ? "取消" : "Cancel"}</button><button className="primary-action" type="submit"><Check size={17} /> {chinese ? "保存" : "Save"}</button></div>
        </form>
      </WorkspaceDialog>
    </section>
  );
}
