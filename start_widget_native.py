from holowidget.paths import log_error
from holowidget.single_instance import ensure_single_instance
from holowidget.widget import LayeredWidget

if __name__ == "__main__":
    # Only enforced when actually launched (not on import), so importing the
    # package for testing/tooling never races a real running instance.
    ensure_single_instance()
    try:
        LayeredWidget().root.mainloop()
    except Exception as error:
        log_error("main", error)
        raise
