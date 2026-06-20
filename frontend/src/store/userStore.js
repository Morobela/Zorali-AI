import { create } from 'zustand'

export const useUserStore = create((set) => ({
  user: null,
  setUser: (user) => set({ user }),
  clearUser: () => {
    localStorage.removeItem('zorali_token')
    set({ user: null })
  },
}))
