"""Surprise bonus points (birthday, loan anniversary, first successful referral). Each
amount is a program setting; 0 means that bonus is off. Every bonus is paid at most once
per occasion, guarded by notification_log."""
from app.services import notify_service
from app.services.points_service import PointsService
from app.services.program_service import get_int_setting


class BonusService:
    @staticmethod
    def _pay(user_id: str, kind: str, ref: str, setting: str, description: str, title: str, body: str) -> bool:
        points = get_int_setting(setting)
        if points <= 0:
            return False
        # Log first: if the same occasion comes round again (retry, second run), nothing is paid twice.
        if not notify_service.log_once(user_id, kind, ref, title.format(points=points), body):
            return False
        PointsService.award_points(user_id=user_id, points=points, type="bonus", description=description)
        notify_service.push(user_id, kind, title.format(points=points), body)
        return True

    @staticmethod
    def birthday(user_id: str, year: int) -> bool:
        return BonusService._pay(user_id, "bonus_birthday", str(year), "bonus_birthday_points",
                                 "Birthday bonus", "Happy birthday! +{points:,} points",
                                 "A little birthday gift from everyone at Reliance.")

    @staticmethod
    def loan_anniversary(user_id: str, year: int, years: int) -> bool:
        label = "1 year" if years == 1 else f"{years} years"
        return BonusService._pay(user_id, "bonus_loan_anniversary", str(year), "bonus_loan_anniversary_points",
                                 f"Loan anniversary bonus ({label})", "Happy loan anniversary! +{points:,} points",
                                 f"Thanks for {label} with Reliance.")

    @staticmethod
    def first_referral(user_id: str, friend_name: str) -> bool:
        return BonusService._pay(user_id, "bonus_first_referral", "first", "bonus_first_referral_points",
                                 "First successful referral bonus", "Bonus! +{points:,} points",
                                 f"Your first successful referral — thanks for introducing {friend_name}.")
