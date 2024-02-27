#include<stdio.h>

void main(unsigned long arg, char* argv[]){

	unsigned long  i;

	for(i=1;i<arg;i++){
		printf("%s ",argv[i]);
	}
	printf("\n");

}
