import { create } from "zustand";

const storedTheme = localStorage.getItem("dgask_theme") || "light";

export const useUiStore = create((set) => ({
  sidebarOpen: true,
  theme: storedTheme,
  toggleSidebar: () => set((state) => ({ sidebarOpen: !state.sidebarOpen })),
  setTheme: (theme) => {
    localStorage.setItem("dgask_theme", theme);
    set({ theme });
  },
}));
