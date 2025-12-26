import { LucideIcon } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';

interface StatsCardProps {
  icon: LucideIcon;
  label: string;
  value: number | string;
  variant?: 'default' | 'success' | 'destructive' | 'warning';
}

export function StatsCard({ icon: Icon, label, value, variant = 'default' }: StatsCardProps) {
  const variantStyles = {
    default: 'bg-secondary text-secondary-foreground',
    success: 'bg-success/10 text-success',
    destructive: 'bg-destructive/10 text-destructive',
    warning: 'bg-warning/10 text-warning',
  };

  return (
    <Card className="animate-scale-in">
      <CardContent className="p-6">
        <div className="flex items-center gap-4">
          <div className={`w-12 h-12 rounded-lg flex items-center justify-center ${variantStyles[variant]}`}>
            <Icon className="w-6 h-6" />
          </div>
          <div>
            <p className="text-sm text-muted-foreground">{label}</p>
            <p className="text-2xl font-bold text-foreground">{value}</p>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
