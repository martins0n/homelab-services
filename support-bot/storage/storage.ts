import { createClient } from '@supabase/supabase-js'
import { DATABASE_KEY, DATABASE_URL } from '../config'

const client = createClient(
  DATABASE_URL, DATABASE_KEY
)


export default client
