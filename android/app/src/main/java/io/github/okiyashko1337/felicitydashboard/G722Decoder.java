package io.github.okiyashko1337.felicitydashboard;

/*
 * ITU G.722 decoder adapted to Java from Android Open Source Project's
 * embdrv/g722/g722_decode.cc. Original implementation by Steve Underwood,
 * placed in the public domain; based in part on CMU Speech Group code (1993).
 */
final class G722Decoder {
    private static final int[] WL={-60,-30,58,172,334,538,1198,3042};
    private static final int[] RL42={0,7,6,5,4,3,2,1,7,6,5,4,3,2,1,0};
    private static final int[] ILB={2048,2093,2139,2186,2233,2282,2332,2383,2435,2489,2543,2599,2656,2714,2774,2834,2896,2960,3025,3091,3158,3228,3298,3371,3444,3520,3597,3676,3756,3838,3922,4008};
    private static final int[] WH={0,-214,798},RH2={2,1,2,1},QM2={-7408,-1616,7408,1616};
    private static final int[] QM4={0,-20456,-12896,-8968,-6288,-4240,-2584,-1200,20456,12896,8968,6288,4240,2584,1200,0};
    private static final int[] QM6={-136,-136,-136,-136,-24808,-21904,-19008,-16704,-14984,-13512,-12280,-11192,-10232,-9360,-8576,-7856,-7192,-6576,-6000,-5456,-4944,-4464,-4008,-3576,-3168,-2776,-2400,-2032,-1688,-1360,-1040,-728,24808,21904,19008,16704,14984,13512,12280,11192,10232,9360,8576,7856,7192,6576,6000,5456,4944,4464,4008,3576,3168,2776,2400,2032,1688,1360,1040,728,432,136,-432,-136};
    private static final int[] QMF_EVEN={3,-11,12,32,-210,951,3876,-805,362,-156,53,-11};
    private static final int[] QMF_ODD={-11,53,-156,362,-805,3876,951,-210,32,12,-11,3};
    private final Band[] band={new Band(),new Band()};private final int[] x=new int[24];
    G722Decoder(){band[0].det=32;band[1].det=8;}

    int decode(byte[] encoded,int offset,int length,short[] pcm){int out=0;for(int j=offset;j<offset+length;j++){
        int code=encoded[j]&255,wd1=code&63,ihigh=(code>>6)&3,wd2=QM6[wd1];wd1>>=2;
        wd2=(band[0].det*wd2)>>15;int rlow=band[0].s+wd2;if(rlow>16383)rlow=16383;else if(rlow< -16384)rlow=-16384;
        wd2=QM4[wd1];int dlowt=(band[0].det*wd2)>>15;wd2=RL42[wd1];wd1=(band[0].nb*127)>>7;wd1+=WL[wd2];if(wd1<0)wd1=0;else if(wd1>18432)wd1=18432;band[0].nb=wd1;
        wd1=(band[0].nb>>6)&31;wd2=8-(band[0].nb>>11);int wd3=wd2<0?ILB[wd1]<<-wd2:ILB[wd1]>>wd2;band[0].det=wd3<<2;block4(band[0],dlowt);
        wd2=QM2[ihigh];int dhigh=(band[1].det*wd2)>>15;int rhigh=dhigh+band[1].s;if(rhigh>16383)rhigh=16383;else if(rhigh< -16384)rhigh=-16384;
        wd2=RH2[ihigh];wd1=(band[1].nb*127)>>7;wd1+=WH[wd2];if(wd1<0)wd1=0;else if(wd1>22528)wd1=22528;band[1].nb=wd1;
        wd1=(band[1].nb>>6)&31;wd2=10-(band[1].nb>>11);wd3=wd2<0?ILB[wd1]<<-wd2:ILB[wd1]>>wd2;band[1].det=wd3<<2;block4(band[1],dhigh);
        System.arraycopy(x,2,x,0,22);x[22]=rlow+rhigh;x[23]=rlow-rhigh;int out1=0,out2=0;for(int i=0;i<12;i++){out2+=x[2*i]*QMF_EVEN[i];out1+=x[2*i+1]*QMF_ODD[i];}pcm[out++]=(short)sat(out1>>11);pcm[out++]=(short)sat(out2>>11);
    }return out;}

    private static void block4(Band b,int value){b.d[0]=value;b.r[0]=sat(b.s+value);b.p[0]=sat(b.sz+value);int sg0=b.p[0]>>15,sg1=b.p[1]>>15,sg2=b.p[2]>>15;int wd1=sat(b.a[1]<<2),wd2=sg0==sg1?-wd1:wd1;if(wd2>32767)wd2=32767;int ap2=(sg0==sg2?128:-128)+(wd2>>7)+((b.a[2]*32512)>>15);if(ap2>12288)ap2=12288;else if(ap2< -12288)ap2=-12288;b.ap[2]=ap2;
        wd1=sg0==sg1?192:-192;wd2=(b.a[1]*32640)>>15;int ap1=sat(wd1+wd2),wd3=sat(15360-b.ap[2]);if(ap1>wd3)ap1=wd3;else if(ap1< -wd3)ap1=-wd3;b.ap[1]=ap1;
        wd1=value==0?0:128;int sz=0;for(int i=1;i<7;i++){int sign=b.d[i]>>15;wd2=sign==(value>>15)?wd1:-wd1;wd3=(b.b[i]*32640)>>15;b.bp[i]=sat(wd2+wd3);}for(int i=6;i>0;i--){b.d[i]=b.d[i-1];b.b[i]=b.bp[i];wd1=sat(b.d[i]+b.d[i]);sz+=(b.b[i]*wd1)>>15;}b.sz=sat(sz);
        for(int i=2;i>0;i--){b.r[i]=b.r[i-1];b.p[i]=b.p[i-1];b.a[i]=b.ap[i];}wd1=sat(b.r[1]+b.r[1]);wd1=(b.a[1]*wd1)>>15;wd2=sat(b.r[2]+b.r[2]);wd2=(b.a[2]*wd2)>>15;b.sp=sat(wd1+wd2);b.s=sat(b.sp+b.sz);
    }
    private static int sat(int value){return value>32767?32767:value< -32768?-32768:value;}
    private static final class Band{int s,sp,sz,nb,det;final int[] r=new int[3],a=new int[3],ap=new int[3],p=new int[3],d=new int[7],b=new int[7],bp=new int[7];}
}
