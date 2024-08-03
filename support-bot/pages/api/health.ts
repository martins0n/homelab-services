import cron from '../../cron';


export default async (req, res) => {
    return res.status(200).json({ status: 'Healthy' })
}