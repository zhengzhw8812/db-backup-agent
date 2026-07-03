import client from './client'
export const login = (username: string, password: string) =>
  client.post('/auth/login', { username, password })
export const logout = () => client.post('/auth/logout')
export const me = () => client.get('/auth/me')
