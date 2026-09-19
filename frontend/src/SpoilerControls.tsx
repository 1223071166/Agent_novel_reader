import { useEffect, useState } from "react";

import { loadReadingSettings, saveReadingSettings } from "./api";
import type { ReadingSettings } from "./types";


type SpoilerControlsProps = {
  bookId: string;
  disabled: boolean;
};

export default function SpoilerControls({ bookId, disabled }: SpoilerControlsProps) {
  const [settings, setSettings] = useState<ReadingSettings | null>(null);
  const [chapterInput, setChapterInput] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    setSettings(null);
    setError("");
    void loadReadingSettings(bookId)
      .then((result) => {
        if (!active) return;
        setSettings(result);
        setChapterInput(String(result.read_through_chapter));
      })
      .catch((requestError) => {
        if (active) {
          setError(requestError instanceof Error ? requestError.message : "加载防剧透设置失败");
        }
      });
    return () => { active = false; };
  }, [bookId]);

  const save = async (spoilerMode: boolean, chapter: number) => {
    if (!settings || saving || disabled) return;
    setSaving(true);
    setError("");
    try {
      const result = await saveReadingSettings(bookId, spoilerMode, chapter);
      setSettings(result);
      setChapterInput(String(result.read_through_chapter));
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "保存防剧透设置失败");
    } finally {
      setSaving(false);
    }
  };

  const saveChapter = () => {
    if (!settings?.spoiler_mode || saving || disabled) return;
    const chapter = Number(chapterInput);
    if (
      chapterInput.trim() === ""
      || !Number.isInteger(chapter)
      || chapter < 0
      || chapter > settings.chapter_count
    ) {
      setError(`章号必须是 0-${settings.chapter_count} 之间的整数`);
      return;
    }
    if (chapter === settings.read_through_chapter) {
      setError("");
      return;
    }
    void save(true, chapter);
  };

  const unavailable = disabled || saving || (settings === null);

  return (
    <div className="spoiler-controls">
      <span className="spoiler-label">防剧透</span>
      <button
        type="button"
        className={`summary-switch spoiler-switch ${settings?.spoiler_mode ? "enabled" : ""}`}
        aria-label="切换防剧透模式"
        aria-pressed={settings?.spoiler_mode ?? false}
        disabled={unavailable}
        onClick={() => settings && void save(
          !settings.spoiler_mode,
          settings.read_through_chapter,
        )}
      >
        <span />
      </button>

      {settings?.spoiler_mode && (
        <label className="spoiler-chapter-inline">
          已读至第
          <input
            type="number"
            min={0}
            max={settings.chapter_count}
            step={1}
            value={chapterInput}
            disabled={disabled || saving}
            aria-label="已阅读章节"
            title={`全书共 ${settings.chapter_count} 章`}
            onChange={(event) => setChapterInput(event.currentTarget.value)}
            onBlur={saveChapter}
            onKeyDown={(event) => {
              if (event.key === "Enter") event.currentTarget.blur();
              if (event.key === "Escape") {
                setChapterInput(String(settings.read_through_chapter));
                setError("");
                event.currentTarget.blur();
              }
            }}
          />
          章
        </label>
      )}

      {error && <span className="spoiler-inline-error" role="alert" title={error}>!</span>}
    </div>
  );
}
