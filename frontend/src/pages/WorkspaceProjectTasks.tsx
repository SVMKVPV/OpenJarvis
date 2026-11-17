import { type FormEvent, useEffect, useRef, useState } from 'react';
import { fetchWorkspaceTasks, saveWorkspaceTask, type WorkspaceTask } from '../lib/api';

export function WorkspaceProjectTasks({ folder, stations, focusTaskId, onDraftContribution, draftingDisabled }: {
  folder: string;
  focusTaskId?: string;
  stations: readonly { id: string; name: string }[];
  onDraftContribution: (task: WorkspaceTask) => void;
  draftingDisabled: boolean;
}) {
  const [tasks, setTasks] = useState<WorkspaceTask[] | null>(null);
  const [title, setTitle] = useState('');
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const focusedTask = useRef<HTMLInputElement>(null);
  const taskToFocus = useRef(focusTaskId);
  useEffect(() => {
    if (!taskToFocus.current || !focusedTask.current) return;
    focusedTask.current.focus();
    taskToFocus.current = undefined;
  }, [tasks]);
  const draft = useRef<Pick<WorkspaceTask, 'id' | 'title'> | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetchWorkspaceTasks(folder, controller.signal).then(
      (items) => { if (!controller.signal.aborted) setTasks(items); },
      () => { if (!controller.signal.aborted) setError('Project tasks could not be loaded.'); },
    );
    return () => controller.abort();
  }, [folder, refresh]);

  const save = async (task: Parameters<typeof saveWorkspaceTask>[1]) => {
    setSaving(true);
    setError('');
    try {
      const saved = await saveWorkspaceTask(folder, task);
      setTasks((current) => {
        const remaining = (current ?? []).filter((item) => item.id !== saved.id);
        return 'title' in task ? [saved, ...remaining] : (current ?? []).map((item) =>
          item.id === saved.id ? saved : item);
      });
      if ('title' in task) {
        draft.current = null;
        setTitle('');
      }
    } catch {
      setError('Project task could not be saved. Try again.');
    } finally {
      setSaving(false);
    }
  };

  const addTask = (event: FormEvent) => {
    event.preventDefault();
    const next = title.trim();
    if (!next || saving || !tasks) return;
    if (draft.current?.title !== next) draft.current = { id: crypto.randomUUID(), title: next };
    void save(draft.current);
  };

  return <section className="connector-editor" aria-label="Project tasks">
    <h3>Project tasks</h3>
    <form className="connector-editor" onSubmit={addTask}>
      <label>Task title
        <input value={title} maxLength={160} disabled={saving}
          onChange={(event) => setTitle(event.target.value)} />
      </label>
      <button disabled={!title.trim() || !tasks || saving}>Add task</button>
    </form>
    {error && <p role="status">{error}</p>}
    {!tasks && (error ? (
      <button type="button" onClick={() => {
        setError('');
        setRefresh((value) => value + 1);
      }}>Retry tasks</button>
    ) : <p role="status">Loading project tasks.</p>)}
    {tasks?.length === 0 && <p>No saved tasks in this folder.</p>}
    {tasks && tasks.length > 0 && <ul>
      {tasks.map((task) => <li key={task.id}>
        <label>
          <input ref={task.id === focusTaskId ? focusedTask : undefined}
            type="checkbox" checked={task.completed} disabled={saving}
            onChange={(event) => void save({ id: task.id, completed: event.target.checked })} />
          {task.title}
        </label>
        <label>Owner
          <select aria-label={`Owner for ${task.title}`} disabled={saving} value={task.station_id ?? ''}
            onChange={(event) => void save({ id: task.id, station_id: event.target.value || null })}>
            <option value="">Unassigned</option>
            {task.station_id && !stations.some((station) => station.id === task.station_id) &&
              <option value={task.station_id}>Unavailable workstation ({task.station_id})</option>}
            {stations.map((station) => <option key={station.id} value={station.id}>{station.name}</option>)}
          </select>
        </label>
        {!task.completed && <button type="button" disabled={saving || draftingDisabled}
          aria-label={`Prepare AI draft for ${task.title}`}
          onClick={() => onDraftContribution(task)}>Prepare AI draft</button>}
      </li>)}
    </ul>}
  </section>;
}
